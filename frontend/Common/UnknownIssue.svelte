<script lang="ts">
    import type { Issue } from "./IssueTypes";

    interface Props {
        issue: Issue;
    }

    let { issue }: Props = $props();
</script>

<pre class="text-muted small">{JSON.stringify(issue, null, 2)}</pre>
