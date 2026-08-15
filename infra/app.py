#!/usr/bin/env python3
import aws_cdk as cdk
from cdk_nag import AwsSolutionsChecks

from config.prod import PROD_CONFIG
from config.staging import STAGING_CONFIG
from stacks.backend_stack import (
    BACKEND_CONTAINER_NAME,
    MIGRATION_CONTAINER_NAME,
    BackendStack,
)
from stacks.deploy_stack import DeployStack
from stacks.frontend_stack import FrontendStack
from stacks.network_stack import NetworkStack

app = cdk.App()

target_env = app.node.try_get_context("env") or "staging"
env_config = PROD_CONFIG if target_env == "prod" else STAGING_CONFIG

aws_env = cdk.Environment(
    account=env_config["account"],
    region=env_config["region"],
)

network = NetworkStack(app, f"{target_env}-network", env=aws_env, env_config=env_config)

backend = BackendStack(
    app,
    f"{target_env}-backend",
    env=aws_env,
    env_config=env_config,
    vpc=network.vpc,
)

frontend = FrontendStack(app, f"{target_env}-frontend", env=aws_env, env_config=env_config)

# CI/CD is GitHub Actions (.github/workflows/). This stack carries no build
# logic — only the OIDC role those workflows assume and the outputs they read.
# The stack name is a contract: deploy.yml looks up `<env>-deploy`.
DeployStack(
    app,
    f"{target_env}-deploy",
    env=aws_env,
    env_config=env_config,
    ecr_repo=backend.ecr_repo,
    cluster=backend.cluster,
    service=backend.service.service,
    backend_task_definition=backend.service.task_definition,
    backend_container_name=BACKEND_CONTAINER_NAME,
    migration_task_definition=backend.migration_task_definition,
    migration_container_name=MIGRATION_CONTAINER_NAME,
    deploy_subnet_ids=backend.deploy_subnet_ids,
    deploy_security_group_id=backend.deploy_security_group.security_group_id,
    deploy_assign_public_ip=backend.deploy_assign_public_ip,
    frontend_bucket=frontend.bucket,
    distribution=frontend.distribution,
)

cdk.Aspects.of(app).add(AwsSolutionsChecks())

app.synth()
