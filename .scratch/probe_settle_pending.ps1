$ErrorActionPreference = "Stop"
$repo = "peroperogames/CITest"
$owner = "peroperogames"
$name = "CITest"
$py = "C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe"

# --- a probe PR -------------------------------------------------------------
$sha = (gh api "repos/$repo/git/ref/heads/master" --jq '.object.sha') -join ""
gh api "repos/$repo/git/refs" -X POST -f ref="refs/heads/probe-settle" -f sha=$sha --jq '.ref' | Out-Null
$b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("a`nb`nc`n"))
$j = @{ message = "test: settle pending probe"; content = $b64; branch = "probe-settle" } | ConvertTo-Json -Compress
[IO.File]::WriteAllText("$env:TEMP\ps.json", $j, [Text.UTF8Encoding]::new($false))
gh api "repos/$repo/contents/probe-settle.md" -X PUT --input "$env:TEMP\ps.json" --jq '.commit.sha' | Out-Null
$pr = (gh api "repos/$repo/pulls" -X POST -f title="probe: settle as a pending review" -f head="probe-settle" -f base="master" -f body="probe" --jq '.number') -join ""
"pr=$pr"

$prId = (gh api graphql -f query='query($o:String!,$n:String!,$p:Int!){repository(owner:$o,name:$n){pullRequest(number:$p){id}}}' -f o=$owner -f n=$name -F p=$pr --jq '.data.repository.pullRequest.id') -join ""

function New-PendingReview($prId, $body) {
  $q = 'mutation($pr: ID!, $body: String!) { addPullRequestReview(input: {pullRequestId: $pr, body: $body}) { pullRequestReview { id state } } }'
  $out = gh api graphql -f query=$q -f pr=$prId -f body=$body | & $py -c "import json,sys; d=json.load(sys.stdin); r=d['data']['addPullRequestReview']['pullRequestReview']; print(r['id'] + ' ' + r['state'])"
  return $out
}

function Submit-Review($revId, $event) {
  $q = 'mutation($rev: ID!, $event: PullRequestReviewEvent!) { submitPullRequestReview(input: {pullRequestReviewId: $rev, event: $event}) { pullRequestReview { state } } }'
  $out = gh api graphql -f query=$q -f rev=$revId -f event=$event | & $py -c "import json,sys; d=json.load(sys.stdin); print(d['data']['submitPullRequestReview']['pullRequestReview']['state'])"
  return $out
}

# --- 1. settle's result, held as a draft and then submitted -----------------
$made = New-PendingReview $prId "未解决线程 5 → 5，暂不 approve。"
"1. created: $made"
$revId = ($made -split ' ')[0]
"1. submitted: " + (Submit-Review $revId "COMMENT")

# --- 2. the approval case, held as a draft and then approved ----------------
$made2 = New-PendingReview $prId "未解决线程 5 → 0，已 approve ✅"
"2. created: $made2"
$revId2 = ($made2 -split ' ')[0]
"2. submitted: " + (Submit-Review $revId2 "APPROVE")

# --- what the pull request shows -------------------------------------------
"=== reviews"
gh api "repos/$repo/pulls/$pr/reviews" --jq '.[] | "id=\(.id) \(.user.login) state=\(.state) body=\((.body // "") | gsub("\n"; " ")) submitted=\(.submitted_at)"'
"pr=$pr"
