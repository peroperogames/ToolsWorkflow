$ErrorActionPreference = "Stop"
$repo = "peroperogames/CITest"
$owner = "peroperogames"
$name = "CITest"

# --- a probe PR -------------------------------------------------------------
$sha = (gh api "repos/$repo/git/ref/heads/master" --jq '.object.sha') -join ""
gh api "repos/$repo/git/refs" -X POST -f ref="refs/heads/probe-pending" -f sha=$sha --jq '.ref' | Out-Null
$src = "line1`nline2`nline3`nline4`n"
$b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($src))
$j = @{ message = "test: pending review probe"; content = $b64; branch = "probe-pending" } | ConvertTo-Json -Compress
[IO.File]::WriteAllText("$env:TEMP\pp.json", $j, [Text.UTF8Encoding]::new($false))
gh api "repos/$repo/contents/probe-pending.md" -X PUT --input "$env:TEMP\pp.json" --jq '.commit.sha' | Out-Null
$pr = (gh api "repos/$repo/pulls" -X POST -f title="probe: pending review API" -f head="probe-pending" -f base="master" -f body="probe") -join ""
$pr = ($pr -split '"number":')[1] -split ',' | Select-Object -First 1
$pr = ($pr -replace '[^0-9]', '')
"pr=$pr"

# --- 1. create a pending review (no event) ----------------------------------
$create = @'
mutation($pr: ID!) {
  addPullRequestReview(input: {pullRequestId: $pr, body: "pending probe"}) {
    pullRequestReview { id state body }
  }
}
'@
$prId = (gh api graphql -f query='query($o:String!,$n:String!,$p:Int!){repository(owner:$o,name:$n){pullRequest(number:$p){id}}}' -f o=$owner -f n=$name -F p=$pr --jq '.data.repository.pullRequest.id') -join ""
"prId=$prId"
$rev = gh api graphql -f query=$create -f pr=$prId | & "C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" -c "import json,sys; d=json.load(sys.stdin); r=d['data']['addPullRequestReview']['pullRequestReview']; print(r['id'], r['state'])"
"created: $rev"
$revId = ($rev -split ' ')[0]

# --- 2. add a thread to that pending review --------------------------------
$thread = @'
mutation($rev: ID!) {
  addPullRequestReviewThread(input: {pullRequestReviewId: $rev, path: "probe-pending.md", line: 2, body: "thread added to a pending review"}) {
    thread { id }
  }
}
'@
$t = gh api graphql -f query=$thread -f rev=$revId 2>&1
"thread: $t"

# --- 3. what does the API say the review is now? ----------------------------
gh api "repos/$repo/pulls/$pr/reviews" --jq '.[] | "id=\(.id) state=\(.state) body=\((.body // "")|length)"'
