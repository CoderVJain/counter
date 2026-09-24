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
