PROD_CONFIG = {
    "environment": "prod",
    "account": "REPLACE_WITH_AWS_ACCOUNT_ID",
    "region": "us-east-1",
    "service_name": "myapp",
    "owner": "platform-team",
    "domain_name": "example.com",
    "frontend_domain": "app.example.com",
    "backend_desired_count": 2,
    "backend_min_tasks": 2,
    "backend_max_tasks": 10,
    # Scopes the OIDC trust policy in deploy_stack.py: only workflow runs from
    # this repo, on this branch, in this GitHub environment may assume the
    # deploy role.
    "github_owner": "REPLACE_WITH_GITHUB_OWNER",
    "github_repo": "REPLACE_WITH_GITHUB_REPO",
    "deploy_branch": "main",
    "github_environment": "production",
    # Set once staging and prod share an account — the OIDC provider is
    # account-wide, so the second stack must reference it rather than create it.
    "github_oidc_provider_arn": None,
}
