"""
Tests for the Jira issue unification backend changes.

Phase 1a: SCT similar-runs includes Jira issues (requires Docker)
Phase 1b: Graphed stats includes Jira issues (requires Docker)
Phase 1c: jira_service derives URL regex from configured server (no Docker)
"""
from dataclasses import asdict
from unittest.mock import patch
from uuid import uuid4

import pytest
from flask import current_app

from argus.backend.models.github_issue import GithubIssue, IssueLink
from argus.backend.models.jira import JiraIssue
from argus.backend.service.jira_service import JiraService, JiraServiceException
from argus.backend.service.views_widgets.graphed_stats import GraphedStatsService
from argus.backend.tests.conftest import get_fake_test_run


@pytest.fixture
def submitted_run(client_service, testrun_service, fake_test):
    """Submit a fresh SCT test run and return the stored run object."""
    run_type, run_req = get_fake_test_run(fake_test)
    client_service.submit_run(run_type, asdict(run_req))
    return testrun_service.get_run(run_type, run_req.run_id)


@pytest.fixture
def saved_jira_issue():
    """Persist a minimal JiraIssue row and return it."""
    issue = JiraIssue(
        user_id=uuid4(),
        key="FROBNICATOR-1234",
        state="todo",
        summary="A Jira test issue",
        project="FROBNICATOR",
        permalink="https://zxqtesting.atlassian.net/browse/FROBNICATOR-1234",
    )
    issue.save()
    return issue


@pytest.fixture
def saved_github_issue():
    """Persist a minimal GithubIssue row and return it."""
    issue = GithubIssue(
        user_id=uuid4(),
        type="issues",
        owner="xyzzy-fake-org",
        repo="quux-fake-repo",
        number=1234,
        state="open",
        title="A GitHub test issue",
        url="https://github.com/xyzzy-fake-org/quux-fake-repo/issues/1234",
    )
    issue.save()
    return issue


def _link_issue_to_run(run, issue) -> IssueLink:
    link = IssueLink()
    link.test_id = run.test_id
    link.run_id = run.id
    link.issue_id = issue.id
    link.type = "issues"
    link.user_id = issue.user_id
    link.save()
    return link


# ---------------------------------------------------------------------------
# Phase 1c – URL parsing (no Docker required)
# ---------------------------------------------------------------------------

@pytest.fixture
def jira_service_factory(app_context):
    """Return a callable that creates a dry-run JiraService for a given server URL.

    The returned service is valid for the lifetime of the test; callers must
    invoke get_issue() inside the same ``patch.dict`` context the factory uses,
    so the fixture yields a context-manager-aware factory:

        with jira_service_factory("https://example.atlassian.net") as svc:
            svc.get_issue(url)
    """
    from contextlib import contextmanager

    @contextmanager
    def _make(jira_server: str):
        with patch.dict(current_app.config, {"JIRA_SERVER": jira_server}):
            yield JiraService(dry_run=True)

    return _make


@pytest.mark.parametrize("jira_server,issue_url", [
    (
        "https://example.atlassian.net",
        "https://example.atlassian.net/browse/PROJ-42",
    ),
    (
        "https://example.atlassian.net",
        "https://example.atlassian.net/browse/PROJ-42/",
    ),
    (
        "http://jira.internal.corp",
        "http://jira.internal.corp/browse/INTERNAL-7",
    ),
])
def test_jira_url_accepted_for_configured_server(jira_server, issue_url, jira_service_factory):
    """URL matching the configured server must not raise a 'no match' exception."""
    with jira_service_factory(jira_server) as svc:
        with pytest.raises(JiraServiceException, match="Jira remote is disabled"):
            svc.get_issue(issue_url)


@pytest.mark.parametrize("jira_server,issue_url,expected_key", [
    (
        "https://example.atlassian.net",
        "https://example.atlassian.net/browse/FROBNICATOR-1234",
        "FROBNICATOR-1234",
    ),
    (
        "https://example.atlassian.net",
        "https://example.atlassian.net/browse/AB-1",
        "AB-1",
    ),
])
def test_jira_url_extracts_correct_key(jira_server, issue_url, expected_key, jira_service_factory):
    """get_issue() must not reject a valid URL; failure must be 'remote disabled', not 'no match'."""
    with jira_service_factory(jira_server) as svc:
        with pytest.raises(JiraServiceException, match="Jira remote is disabled"):
            svc.get_issue(issue_url)


@pytest.mark.parametrize("jira_server,issue_url", [
    (
        "https://example.atlassian.net",
        "https://other.atlassian.net/browse/PROJ-42",
    ),
    (
        "https://example.atlassian.net",
        "https://github.com/xyzzy-fake-org/quux-fake-repo/issues/1",
    ),
    (
        "https://example.atlassian.net",
        "https://example.atlassian.net/issues/PROJ-42",
    ),
    (
        "https://example.atlassian.net",
        "https://example.atlassian.net/browse/proj-42",
    ),
    # A different configured server must NOT match example.atlassian.net URLs.
    (
        "https://mycompany.atlassian.net",
        "https://example.atlassian.net/browse/FROBNICATOR-1",
    ),
])
def test_jira_url_rejected(jira_server, issue_url, jira_service_factory):
    """URL not matching the configured server must raise 'URL doesn't match' exception."""
    with jira_service_factory(jira_server) as svc:
        with pytest.raises(JiraServiceException, match="URL doesn't match configured Jira server"):
            svc.get_issue(issue_url)


# ---------------------------------------------------------------------------
# Phase 1a – SCT / issue_service returns Jira issues (Docker required)
# ---------------------------------------------------------------------------

@pytest.mark.docker_required
def test_jira_issue_returned_for_run(submitted_run, saved_jira_issue, issue_service):
    """issue_service.get() must include a Jira issue linked to a run."""
    _link_issue_to_run(submitted_run, saved_jira_issue)

    issues = issue_service.get("run_id", str(submitted_run.id), False)
    jira_issues = [i for i in issues if i.get("subtype") == "jira"]
    found = next((i for i in jira_issues if str(i["id"]) == str(saved_jira_issue.id)), None)

    assert found is not None, f"Jira issue {saved_jira_issue.id} missing from {issues}"
    assert found["key"] == saved_jira_issue.key
    assert found["state"] == saved_jira_issue.state
    assert found["summary"] == saved_jira_issue.summary
    assert found["project"] == saved_jira_issue.project
    assert found["permalink"] == saved_jira_issue.permalink
    assert found["subtype"] == "jira"


@pytest.mark.docker_required
def test_github_and_jira_issues_returned_together(
    submitted_run, saved_github_issue, saved_jira_issue, issue_service
):
    """Both GitHub and Jira issues linked to the same run must be returned."""
    _link_issue_to_run(submitted_run, saved_github_issue)
    _link_issue_to_run(submitted_run, saved_jira_issue)

    issues = issue_service.get("run_id", str(submitted_run.id), False)

    gh_found = next((i for i in issues if str(i["id"]) == str(saved_github_issue.id)), None)
    assert gh_found is not None, f"GitHub issue {saved_github_issue.id} missing from {issues}"
    assert gh_found["type"] == saved_github_issue.type
    assert gh_found["owner"] == saved_github_issue.owner
    assert gh_found["repo"] == saved_github_issue.repo
    assert gh_found["number"] == saved_github_issue.number
    assert gh_found["state"] == saved_github_issue.state
    assert gh_found["title"] == saved_github_issue.title
    assert gh_found["url"] == saved_github_issue.url
    assert gh_found["subtype"] == "github"

    jira_found = next((i for i in issues if str(i["id"]) == str(saved_jira_issue.id)), None)
    assert jira_found is not None, f"Jira issue {saved_jira_issue.id} missing from {issues}"
    assert jira_found["key"] == saved_jira_issue.key
    assert jira_found["state"] == saved_jira_issue.state
    assert jira_found["summary"] == saved_jira_issue.summary
    assert jira_found["project"] == saved_jira_issue.project
    assert jira_found["permalink"] == saved_jira_issue.permalink
    assert jira_found["subtype"] == "jira"


# ---------------------------------------------------------------------------
# Phase 1b – graphed_stats serialization (Docker required)
# ---------------------------------------------------------------------------

@pytest.mark.docker_required
def test_graphed_stats_includes_jira_issue(submitted_run, saved_jira_issue):
    """Graphed stats response must include Jira issues with all expected fields."""
    _link_issue_to_run(submitted_run, saved_jira_issue)

    result = GraphedStatsService().get_runs_details([str(submitted_run.id)])
    run_issues = result[str(submitted_run.id)]["issues"]
    found = next((i for i in run_issues if i.get("key") == saved_jira_issue.key), None)

    assert found is not None, f"Jira issue {saved_jira_issue.key} missing from {run_issues}"
    assert found == {
        "subtype": "jira",
        "key": saved_jira_issue.key,
        "state": saved_jira_issue.state,
        "summary": saved_jira_issue.summary,
        "permalink": saved_jira_issue.permalink,
    }


@pytest.mark.docker_required
def test_graphed_stats_includes_github_issue(submitted_run, saved_github_issue):
    """Graphed stats response must include GitHub issues with all expected fields."""
    _link_issue_to_run(submitted_run, saved_github_issue)

    result = GraphedStatsService().get_runs_details([str(submitted_run.id)])
    run_issues = result[str(submitted_run.id)]["issues"]
    found = next((i for i in run_issues if i.get("number") == saved_github_issue.number), None)

    assert found is not None, f"GitHub issue #{saved_github_issue.number} missing from {run_issues}"
    assert found == {
        "subtype": "github",
        "number": saved_github_issue.number,
        "state": saved_github_issue.state,
        "title": saved_github_issue.title,
        "url": saved_github_issue.url,
    }


@pytest.mark.docker_required
def test_graphed_stats_run_with_no_issues(submitted_run):
    """A run with no linked issues must appear with an empty issues list."""
    result = GraphedStatsService().get_runs_details([str(submitted_run.id)])
    assert result[str(submitted_run.id)]["issues"] == []


@pytest.mark.docker_required
@pytest.mark.parametrize("subtype", ["github", "jira"])
def test_graphed_stats_issue_has_required_subtype_field(
    submitted_run, saved_github_issue, saved_jira_issue, subtype
):
    """Every issue in the graphed stats response must carry a subtype field."""
    _link_issue_to_run(submitted_run, saved_github_issue)
    _link_issue_to_run(submitted_run, saved_jira_issue)

    result = GraphedStatsService().get_runs_details([str(submitted_run.id)])
    run_issues = result[str(submitted_run.id)]["issues"]
    matching = [i for i in run_issues if i.get("subtype") == subtype]
    assert len(matching) >= 1, f"No issues with subtype='{subtype}' found in {run_issues}"
