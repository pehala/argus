<script lang="ts">
    import { getKey, getTitle, getUrl, GithubIssueColorMap, JiraIssueColorMap } from "./IssueTypes";
    import type { Issue } from "./IssueTypes";

    interface Props {
        issue: Issue;
    }

    let { issue }: Props = $props();

    const url = $derived(getUrl(issue));
    const key = $derived(getKey(issue));
    const title = $derived(getTitle(issue));
    const colorClass = $derived(
        issue.subtype === "github"
            ? GithubIssueColorMap[issue.state as "open" | "closed"] ?? "issue-closed"
            : JiraIssueColorMap[issue.state as keyof typeof JiraIssueColorMap] ?? "jira-new"
    );
</script>

<a
    href={url}
    target="_blank"
    class="badge me-1 issue-badge {colorClass}"
    title={title}
>
    {key}
</a>

<style>
    .issue-badge {
        text-decoration: none;
        font-size: 0.8em;
    }

    .issue-badge:hover {
        opacity: 0.8;
    }
</style>
