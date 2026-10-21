\# Saathi: friction log (Amazon Developer Hackathon, Alexa+ track)



| # | Task attempted | Steps taken | Expected | Actual | Severity | Workaround | Suggestion |

|---|---|---|---|---|---|---|---|

| 1 | Install the Alexa AI CLI to connect our MCP server to Alexa+ | Followed "Set Up Your Development Environment" in the Alexa+ MCP Toolkit docs | `npm install -g @alexa-ai/cli`, then sign in with an Amazon developer account | Install requires an AWS IAM user, an assumed role and a login to a private AWS CodeArtifact npm registry. We have no AWS account, and hackathon credits ran out on Oct 7 | \*\*High (blocking)\*\* | Took the simulated Alexa+ path; kept the MCP server real and spec-compliant | Publish the CLI on public npm with Login with Amazon only |

| 2 | Plan authentication for the add-on | Compared the Alexa+ auth checklist with the MCP 2025-11-25 authorization spec | A spec-compliant MCP server works as-is | Alexa+ wants a `401` \*\*without\*\* `WWW-Authenticate`; the MCP spec expects the header | Medium | Deferred auth to the roadmap | Align with the spec, or document the reason and the exact differences |

| 3 | Prepare a development-stage deploy | Read the `addon.json` schema | A minimal manifest is enough for dev testing | 6 icon sizes, a carousel image and privacy/terms URLs are required up front | Medium | n/a (blocked earlier by #1) | Require media and legal fields only at certification |

| 4 | Check whether we could test from India | Read the QuickStart and manifest examples | Clear guidance on non-US developer testing and locales | Examples only show `distributionCountries: \["US"]` and `en-US` | Medium | Built and demoed with simulated devices | Document dev-testing availability for India and support en-IN / hi-IN |

| 5 | Serve our MCP server through a tunnel | Ran it behind `cloudflared` as the docs suggest | Requests reach the server | MCP Python SDK v2 DNS-rebinding protection returned 421 for the tunnel's Host header | Low | `cloudflared ... --http-host-header 127.0.0.1:8000` | Mention this flag in the Alexa+ tunnelling tip |

| 6 | Request hackathon AWS credits | Went to the credit request form | $150 AWS credits | Codes ran out on Oct 7 | Low | Built at zero cost with free tools | Show remaining stock on the main hackathon page |

