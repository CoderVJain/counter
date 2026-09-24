
# Friction log

Developer-experience friction hit while building Counter on Amazon and AWS tooling.
One entry per problem: what was attempted, what happened, severity, workaround, suggestion.

## 1. No public path to test an Alexa+ add-on

- **Date:** 2026-09-24
- **Task:** Find the supported way to run an MCP server against Alexa+ for the Alexa+ track.
- **Steps:** Read the Alexa+ add-on docs (MCP Toolkit overview, quickstart, add-on API reference) and the
  hackathon rules and resources pages.
- **Expected:** A developer-accessible simulator or dev-stage deployment, as the docs' quickstart implies.
- **Actual:** The MCP Toolkit, add-on registration and the Alexa AI CLI are partner-gated, and the toolkit is
  described as available in the United States only. The hackathon resources page links the MCP spec but offers
  no reference add-on or test harness. Entrants outside the partner program cannot exercise the real host.
- **Severity:** High. It removes the track's headline integration from reach and forces every entrant to build
  a stand-in host before writing a single tool.
- **Workaround:** Take the rules' sanctioned simulated-Alexa+ path and build our own MCP client
  (`sim_client/`) over Streamable HTTP.
- **Suggestion:** Publish a read-only reference MCP host, or a hosted sandbox that accepts any public
  Streamable HTTP endpoint, so tool descriptions and card rendering can be tested against real Alexa+
  behaviour. Failing that, state the gating plainly at the top of the add-on docs, since the quickstart
  currently reads as generally available.

## 2. boto3 ignores the OS trust store, so TLS-inspecting antivirus breaks every AWS call

- **Date:** 2026-09-24
- **Task:** Make the first Bedrock Nova call from a Windows developer machine.
- **Steps:** `aws configure`, then a `boto3` `sts.get_caller_identity()` plus `bedrock-runtime.converse()`.
- **Expected:** An auth result, or a clear auth error.
- **Actual:** `botocore.exceptions.SSLError: SSL validation failed for https://sts.us-east-1.amazonaws.com/
  [SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer certificate`. The machine runs Avast, whose
  Web/Mail Shield re-signs HTTPS with a private CA that is present and trusted in the Windows root store.
  botocore verifies against the bundled certifi file only, so it rejects a certificate the OS accepts.
- **Severity:** Medium, but high-friction for a first-time builder. The error arrives at the first credentialed
  call, so it reads as an authentication or permissions problem. A beginner's natural next moves - recreate the
  access key, re-check the IAM policy, re-run `aws configure` - all fail, and the real cause (consumer
  antivirus) is never mentioned in any AWS getting-started material. Common advice online is `verify=False`,
  which silently disables certificate validation on the channel that carries the credentials.
- **Workaround:** `counter/tls.py` dumps the Windows ROOT and CA stores to a PEM and sets `AWS_CA_BUNDLE`.
  Note that `truststore.inject_into_ssl()`, the usual Python answer, is **incompatible** with botocore: it
  recurses infinitely in `botocore.httpsession.create_urllib3_context` and dies with `RecursionError`.
- **Suggestion:** Have botocore fall back to the OS trust store when certifi verification fails on Windows and
  macOS, or ship a documented `use_system_certs` option. Failing that, detect `CERTIFICATE_VERIFY_FAILED` and
  extend the error message with a pointer to `AWS_CA_BUNDLE` and the likelihood of TLS-inspecting software.
  Fixing the `truststore` recursion would also let builders use the standard ecosystem tool.

## 3. New-account verification surfaces as AccessDeniedException on Bedrock

- **Date:** 2026-09-24
- **Task:** First `bedrock-runtime.converse()` call with Nova Micro on a new account.
- **Steps:** Created an IAM user with `AmazonBedrockFullAccess`, configured credentials, called STS then Converse.
- **Expected:** Either a model response, or an error naming the actual cause.
- **Actual:** STS `get_caller_identity` succeeded, so credentials and IAM were demonstrably fine. Converse then
  raised `AccessDeniedException: Your account is currently being verified. Verification normally takes less
  than 2 hours.`
- **Severity:** Low once understood, medium in the moment. `AccessDeniedException` is the same error class used
  for genuine IAM denials, so the obvious response is to go and edit policies that were never wrong. The
  message body carries the real reason, but any tooling that surfaces only the error type will mislead.
- **Workaround:** Wait, then retry. Build the credential-free layers meanwhile.
- **Suggestion:** Use a distinct error code for pending account verification, or state the expected wait and
  the verification status in the Bedrock console so a builder can tell "not yet" from "not allowed". Mentioning
  the hold in the Bedrock getting-started page would prevent the misdiagnosis entirely.

## 4. New accounts cannot invoke any Bedrock model: "ValidationException: Operation not allowed"

- **Date:** 2026-09-24
- **Task:** Make the first Nova Micro call after account verification completed.
- **Steps:** Verified identity with STS (succeeds). Called `Converse` and `InvokeModel`, with both the
  foundation model id `amazon.nova-micro-v1:0` and the inference profile `us.amazon.nova-micro-v1:0`.
  `ListFoundationModels` reports both Nova models as `ON_DEMAND`-capable, and `ListInferenceProfiles` reports
  `us.amazon.nova-micro-v1:0` and `us.amazon.nova-lite-v1:0` as ACTIVE.
- **Expected:** A model response, since the console lists the models as available and IAM grants
  `AmazonBedrockFullAccess`.
- **Actual:** Every combination fails with `ValidationException: Operation not allowed`. Read operations
  (`ListFoundationModels`, `ListInferenceProfiles`) succeed against the same credentials, so the account can
  see the models it cannot invoke.
- **Severity:** High, and blocking. It stops all model work on a new account, and the error is actively
  misleading three times over: `ValidationException` implies a malformed request, "Operation not allowed"
  implies a permissions or policy problem, and the model access page (now retired) says serverless models are
  enabled automatically on first invoke. None of those point at the real cause, which is an account-standing
  gate tied to billing history. Community threads show the same confusion at length, with the remedy being a
  support case rather than anything the builder can fix.
- **Also observed:** the block is not quite absolute. One `Converse` call to `us.amazon.nova-micro-v1:0` in
  `us-west-2` succeeded, and six identical calls immediately afterwards failed with the same
  `ValidationException`. The entitlement therefore exists but is enforced inconsistently, which makes the
  failure look like a transient bug rather than a deliberate account gate and sends builders hunting for a
  fault in their own code.
- **Workaround:** Open a free "Account and billing" support case. Meanwhile develop against the fallback LLM
  provider behind `counter/agent/llm.py`, so the parser work is not blocked.
- **Suggestion:** Return a distinct error code such as `AccountNotEligibleException` with the actual reason and
  the remediation path, rather than `ValidationException`. Better still, surface invocation eligibility in the
  Bedrock console next to the model list, so a builder can see "visible but not yet invocable" without writing
  code to discover it. This is the first thing a new builder does with Bedrock, and it currently fails with an
  error that sends them to rewrite their IAM policy.
