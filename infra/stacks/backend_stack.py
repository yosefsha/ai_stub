from aws_cdk import Duration, RemovalPolicy, Stack, Tags
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_ecs_patterns as ecs_patterns
from aws_cdk import aws_logs as logs
from constructs import Construct


# Container names are contract, not decoration: .github/workflows/deploy.yml
# re-images containers by name via amazon-ecs-render-task-definition, and the
# name reaches it through the deploy stack's CfnOutputs.
BACKEND_CONTAINER_NAME = "backend"
MIGRATION_CONTAINER_NAME = "migration"


class BackendStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        env_config: dict,
        vpc: ec2.IVpc,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.ecr_repo = ecr.Repository(
            self,
            "BackendRepo",
            repository_name=f"{env_config['service_name']}-backend",
            removal_policy=RemovalPolicy.RETAIN,
            lifecycle_rules=[ecr.LifecycleRule(max_image_count=20)],
        )

        self.cluster = ecs.Cluster(
            self, "Cluster", vpc=vpc, container_insights_v2=ecs.ContainerInsights.ENABLED
        )

        log_group = logs.LogGroup(
            self,
            "BackendLogs",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
        )

        self.service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self,
            "BackendService",
            cluster=self.cluster,
            cpu=256,
            memory_limit_mib=512,
            desired_count=env_config["backend_desired_count"],
            task_image_options=ecs_patterns.ApplicationLoadBalancedTaskImageOptions(
                # `:latest` is a bootstrap tag only. deploy.yml registers a new
                # revision pinned to the commit SHA on every deploy; this tag
                # exists so a brand-new environment has something to pull before
                # the workflow has ever run.
                image=ecs.ContainerImage.from_ecr_repository(self.ecr_repo),
                container_name=BACKEND_CONTAINER_NAME,
                container_port=8000,
                log_driver=ecs.LogDrivers.aws_logs(
                    stream_prefix="backend",
                    log_group=log_group,
                ),
            ),
            public_load_balancer=True,
            # Rolls a release back when its tasks never pass /health. deploy.yml
            # waits for service stability, so a rollback surfaces as a failed
            # deploy rather than a green job over a silently reverted service.
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
            min_healthy_percent=100,
            max_healthy_percent=200,
        )

        self.service.target_group.configure_health_check(
            path="/health",
            healthy_http_codes="200",
            interval=Duration.seconds(30),
        )

        scaling = self.service.service.auto_scale_task_count(
            min_capacity=env_config["backend_min_tasks"],
            max_capacity=env_config["backend_max_tasks"],
        )
        scaling.scale_on_cpu_utilization("CpuScaling", target_utilization_percent=70)

        # Migrations run as a one-off Fargate task in the same VPC and security
        # group as the service, not from the GitHub runner: the database sits in
        # private subnets and admits only this security group. deploy.yml runs
        # this definition to completion and checks its exit code before it
        # updates the service.
        self.migration_task_definition = ecs.FargateTaskDefinition(
            self,
            "MigrationTask",
            cpu=256,
            memory_limit_mib=512,
        )
        self.migration_task_definition.add_container(
            "Migration",
            container_name=MIGRATION_CONTAINER_NAME,
            image=ecs.ContainerImage.from_ecr_repository(self.ecr_repo),
            command=["alembic", "upgrade", "head"],
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="migration",
                log_group=log_group,
            ),
        )

        # The subnets the migration task launches into. Private, so no public IP
        # is assigned — outbound to ECR goes through the NAT Gateway in
        # network_stack.py. Remove that NAT and this has to become a public
        # subnet with assign_public_ip enabled, or the task never pulls its image.
        self.deploy_subnet_ids = vpc.select_subnets(
            subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
        ).subnet_ids
        # The service's own security group, not a second one: it is the source a
        # database ingress rule admits, so the migration task has to run in it.
        # Taking it from the service rather than passing one in also keeps the
        # ALB's egress rule inside this stack — a shared security group defined
        # in network_stack.py makes that rule a cross-stack write and CDK
        # rejects the resulting cycle.
        self.deploy_security_group = self.service.service.connections.security_groups[0]
        self.deploy_assign_public_ip = "DISABLED"

        Tags.of(self).add("Environment", env_config["environment"])
        Tags.of(self).add("Service", env_config["service_name"])
        Tags.of(self).add("Owner", env_config["owner"])
