"""The AWS half of the GitHub Actions deploy.

Replaces the CodePipeline/CodeBuild stack this repo used to carry. It holds no
build logic — that lives in .github/workflows/ — only the two things a workflow
cannot create for itself:

  1. A role GitHub can assume over OIDC, so no AWS key is ever stored in the
     repository.
  2. CfnOutputs naming the resources to deploy into, so the workflow reads them
     from CloudFormation instead of hardcoding names it cannot verify.

The output keys below are a contract with .github/workflows/deploy.yml, which
reads them with `jq -er` and fails the job when one is missing. Renaming a key
here breaks the deploy; change both together.
"""

from aws_cdk import CfnOutput, Duration, Stack, Tags
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from constructs import Construct

GITHUB_OIDC_URL = "https://token.actions.githubusercontent.com"
GITHUB_OIDC_AUDIENCE = "sts.amazonaws.com"


class DeployStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        env_config: dict,
        ecr_repo: ecr.IRepository,
        cluster: ecs.ICluster,
        service: ecs.IBaseService,
        backend_task_definition: ecs.TaskDefinition,
        backend_container_name: str,
        migration_task_definition: ecs.TaskDefinition,
        migration_container_name: str,
        deploy_subnet_ids: list[str],
        deploy_security_group_id: str,
        deploy_assign_public_ip: str,
        frontend_bucket: s3.IBucket,
        distribution: cloudfront.IDistribution,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # One provider per account, not per environment. When staging and prod
        # share an account the second stack to deploy would collide on it, so
        # point `github_oidc_provider_arn` at the existing one instead.
        existing_provider_arn = env_config.get("github_oidc_provider_arn")
        if existing_provider_arn:
            provider = iam.OpenIdConnectProvider.from_open_id_connect_provider_arn(
                self, "GitHubOidcProvider", existing_provider_arn
            )
        else:
            provider = iam.OpenIdConnectProvider(
                self,
                "GitHubOidcProvider",
                url=GITHUB_OIDC_URL,
                client_ids=[GITHUB_OIDC_AUDIENCE],
            )

        repo = f"{env_config['github_owner']}/{env_config['github_repo']}"

        # Which workflow runs may assume this role. Scoped to the deploying
        # branch and to the GitHub environment whose required reviewers are the
        # human gate — `repo:<owner>/<repo>:*` would let a pull request from a
        # fork deploy production.
        principal = iam.WebIdentityPrincipal(
            provider.open_id_connect_provider_arn,
            {
                "StringEquals": {
                    f"{GITHUB_OIDC_URL.removeprefix('https://')}:aud": GITHUB_OIDC_AUDIENCE,
                },
                "StringLike": {
                    f"{GITHUB_OIDC_URL.removeprefix('https://')}:sub": [
                        f"repo:{repo}:ref:refs/heads/{env_config['deploy_branch']}",
                        f"repo:{repo}:environment:{env_config['github_environment']}",
                    ],
                },
            },
        )

        # The name is fixed and derivable on purpose: deploy.yml builds this ARN
        # from AWS_ACCOUNT_ID, SERVICE_NAME and the environment before it holds
        # any credential to look it up with.
        role_name = f"{env_config['service_name']}-{env_config['environment']}-github-actions-deploy"

        self.deploy_role = iam.Role(
            self,
            "GitHubActionsDeployRole",
            role_name=role_name,
            assumed_by=principal,
            description=f"Assumed over OIDC by {repo} to deploy {env_config['environment']}",
            # Long enough for the migration task and the service-stability wait,
            # which deploy.yml caps at 20 minutes each.
            max_session_duration=Duration.hours(1),
        )

        # Read the stack outputs below.
        self.deploy_role.add_to_policy(
            iam.PolicyStatement(
                actions=["cloudformation:DescribeStacks"],
                resources=[self.stack_id],
            )
        )

        # Push the image. GetAuthorizationToken is account-wide by API design —
        # it takes no resource — so it cannot be narrowed to this repository.
        self.deploy_role.add_to_policy(
            iam.PolicyStatement(actions=["ecr:GetAuthorizationToken"], resources=["*"])
        )
        ecr_repo.grant_pull_push(self.deploy_role)

        # Register a revision pinned to this commit's image, roll the service,
        # and run the migration task.
        self.deploy_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ecs:DescribeTaskDefinition",
                    "ecs:RegisterTaskDefinition",
                ],
                # Neither action accepts a resource ARN.
                resources=["*"],
            )
        )
        self.deploy_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ecs:DescribeServices", "ecs:UpdateService"],
                resources=[service.service_arn],
            )
        )
        self.deploy_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ecs:RunTask", "ecs:DescribeTasks", "ecs:StopTask"],
                resources=[
                    f"arn:aws:ecs:{self.region}:{self.account}:task-definition/{migration_task_definition.family}:*",
                    f"arn:aws:ecs:{self.region}:{self.account}:task/{cluster.cluster_name}/*",
                ],
                conditions={"ArnEquals": {"ecs:cluster": cluster.cluster_arn}},
            )
        )

        # Registering a revision hands ECS the task and execution roles, and
        # RegisterTaskDefinition is a privilege-escalation path without this
        # being narrowed to exactly the roles these definitions already use.
        passable_roles = [
            role
            for role in (
                backend_task_definition.task_role,
                backend_task_definition.execution_role,
                migration_task_definition.task_role,
                migration_task_definition.execution_role,
            )
            if role is not None
        ]
        self.deploy_role.add_to_policy(
            iam.PolicyStatement(
                actions=["iam:PassRole"],
                resources=[role.role_arn for role in passable_roles],
                conditions={"StringEquals": {"iam:PassedToService": "ecs-tasks.amazonaws.com"}},
            )
        )

        # Publish the SPA. `aws s3 sync --delete` needs list and delete as well
        # as write.
        frontend_bucket.grant_read_write(self.deploy_role)
        frontend_bucket.grant_delete(self.deploy_role)

        self.deploy_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "cloudfront:CreateInvalidation",
                    # The workflow waits for the invalidation to complete.
                    "cloudfront:GetInvalidation",
                ],
                resources=[
                    f"arn:aws:cloudfront::{self.account}:distribution/{distribution.distribution_id}"
                ],
            )
        )

        # ------------------------------------------------------------------
        # The contract with deploy.yml.
        # ------------------------------------------------------------------
        CfnOutput(self, "DeployRoleArn", value=self.deploy_role.role_arn)
        CfnOutput(self, "EcrRepositoryUri", value=ecr_repo.repository_uri)
        CfnOutput(self, "EcsClusterName", value=cluster.cluster_name)
        CfnOutput(self, "EcsServiceName", value=service.service_name)
        CfnOutput(self, "BackendTaskDefinitionFamily", value=backend_task_definition.family)
        CfnOutput(self, "BackendContainerName", value=backend_container_name)
        CfnOutput(self, "MigrationTaskDefinitionFamily", value=migration_task_definition.family)
        CfnOutput(self, "MigrationContainerName", value=migration_container_name)
        CfnOutput(self, "DeploySubnetIds", value=",".join(deploy_subnet_ids))
        CfnOutput(self, "DeploySecurityGroupId", value=deploy_security_group_id)
        CfnOutput(self, "DeployAssignPublicIp", value=deploy_assign_public_ip)
        CfnOutput(self, "FrontendBucketName", value=frontend_bucket.bucket_name)
        CfnOutput(self, "CloudFrontDistributionId", value=distribution.distribution_id)

        Tags.of(self).add("Environment", env_config["environment"])
        Tags.of(self).add("Service", env_config["service_name"])
        Tags.of(self).add("Owner", env_config["owner"])
