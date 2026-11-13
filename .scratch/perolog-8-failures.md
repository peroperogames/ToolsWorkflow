# PeroLog #8 — the 11 PlayMode failures (from the run's own report)

Source: the checks run of 2026-10-21 09:34 UTC (ai-review .87), the first run in
which the PlayMode suite finished at all (Test Framework raised to 1.4.6).

The full NUnit XML is on the runner:

    /tmp/ai-code-review/peroperogames/PeroLog-PR8/.ai-review/tests-PlayMode.xml

and from this release onward it is also uploaded with the job as the artifact
`ai-review-reports-<run_id>-<run_attempt>`.

## Failing cases

| # | case | message |
|---|---|---|
| 1 | InitDirLogUploaderTests.AutoUploadHonorsMaxUploadCountTest(1) | AssertionException: Auto upload should honor MaxUploadCountPerTime |
| 2 | InitDirLogUploaderTests.AutoUploadHonorsMaxUploadCountTest(3) | same |
| 3 | InitDirLogUploaderTests.AutoUploadHonorsMaxUploadCountTest(5) | same |
| 4 | InitDirLogUploaderTests.ManualUploadCleansStaleMemoBeforeRotationTest | The frozen current log should be uploaded after rotation |
| 5 | InitDirLogUploaderTests.ManualUploadExcludesActiveLoggingFileTest | Manual upload should upload the frozen snapshot and exclude the active log file |
| 6 | InitDirLogUploaderTests.ManualUploadIgnoresMaxUploadCountAndKeepsMemoTest | Automatic upload should honor MaxUploadCountPerTime |
| 7 | InitDirLogUploaderTests.ManualUploadIgnoresMaxUploadCountTest | Manual upload should ignore MaxUploadCountPerTime |
| 8 | InitDirLogUploaderTests.ManualUploadSuccessTest | (no message in the summary) |
| 9 | InitDirLogUploaderTests.UploadFailedTest | System.NullReferenceException |
| 10 | InitDirLogUploaderTests.UploadPartiallyFailedTest | System.NullReferenceException |
| 11 | InitDirLogUploaderTests.UploadSuccessTest | (no message in the summary) |

## What was checked

- The same class passes 19/19 on Windows, both in batch mode (`unity test`) and
  in a windowed editor, in a project configured exactly as the pipeline does
  (UPM package as `file:` dependency, testables, UTF 1.4.6, Moq, registries).
  So the difference is the operating system, not the mode.
- `BaseLogUploader.AddLogFilesToCache` orders files by `CreationTimeUtc`, and the
  tests force an order with `new FileInfo(path).CreationTime = now + i*500ms`.
  On Windows that setter takes effect; on Linux it does not give a usable
  creation time, so the six files compare equal and the order becomes whatever
  `Directory.GetFiles` returns — which is what the max-count assertions and the
  NullReferenceExceptions look like.
- `ManualUploadCleansStaleMemoBeforeRotationTest` is a different matter: this PR
  removed the memo cleanup from `UpdateLoggingFile` (the -32 lines in
  `BaseLogUploader.cs`), which is exactly the behaviour that test asserts.