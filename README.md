\# Saathi: an Alexa+ care companion for parents who live alone



\*\*Saathi\*\* (Hindi for "companion") is an Alexa+ MCP add-on for elderly parents who live alone while their children work in other cities, and for those children.



Kamla, 72, lives in Jaipur. Her son Rohan is in Bengaluru. Kamla talks to Alexa like she would to a person: \*"I took my BP tablet."\* \*"I'm feeling dizzy again."\* Saathi remembers across days, notices patterns a single conversation can't (dizziness three times in a week \*\*while blood-pressure doses were being missed\*\*), suggests a doctor's home visit, and asks Rohan to approve it. Nothing is booked until family says yes. If Kamla ever says she fell or has chest pain, Saathi tells her to call 112 and alerts the whole family at once.



> Built during the \*\*Build, Ship, Shape: Amazon Developer Hackathon\*\* (Alexa+ track).



\## What's in this repo



| File | What it is |

| --- | --- |

| `server.py` | The \*\*Saathi MCP server\*\*: 8 tools over \*\*Streamable HTTP\*\* (MCP Python SDK v2, serves 2025-11-25 clients) |

| `store.py` | Persistent memory (SQLite) and the \*\*care-signal engine\*\* that scores the week and explains why |

| `alexa\_sim.py` + `sim.html` | The \*\*simulated Alexa+ experience\*\*: an Echo Show in Kamla's home and Rohan's phone, with real voice in and out, driven by an LLM agent that calls the real Saathi MCP server |

| `demo.py` | Plays the full story against any Saathi URL and times every tool call |



\## How it works



```mermaid

flowchart LR

&#x20; K\["Kamla - Echo Show (Jaipur)"] -- voice --> A\["Alexa+ agent<br/>(simulated: LLM with tool calling)"]

&#x20; R\["Rohan - phone (Bengaluru)"] -- voice --> A

&#x20; A -- "MCP over Streamable HTTP" --> S\["Saathi MCP server"]

&#x20; S --> M\[("Memory: medicines, doses,<br/>check-ins, alerts, requests")]

&#x20; S --> E\["Care-signal engine<br/>(7-day patterns, risk level, reasons)"]

&#x20; S --> Q\["Approval-gated care requests<br/>(doctor, lab test, nurse, refill)"]

```



\### The 8 tools



| For | Tool | What it does |

| --- | --- | --- |

| Parent | `log\_medicine` | "I took my BP tablet": matches how people \*describe\* medicines to the real one and the right time slot |

| Parent | `medicines\_today` | What's taken, due and still to come today |

| Parent | `check\_in` | Records how she feels in her own words (English and common Hindi words like \*chakkar\*), detects symptoms, mood and emergencies, and checks the week's pattern |

| Parent | `request\_care` | Asks for a doctor's visit, home lab test, nurse, refill or groceries. \*\*Waits for family approval\*\* |

| Parent | `care\_request\_status` | "Is the doctor coming?" |

| Family | `family\_briefing` | How the parent is doing this week, why, and what's waiting for a decision |

| Family | `decide\_care\_request` | Approve (books it) or decline |

| Family | `add\_medicine` | Manage the medicine list |



Every tool returns a `say` field written to be spoken aloud, plus structured data.



\### Design choices



\- \*\*Patterns, not diagnoses.\*\* Saathi never diagnoses. It notices patterns across days and brings in family and doctors.

\- \*\*Family stays in control of money and bookings.\*\* Bookings are approval-gated tasks: requested, then awaiting family approval, then booked or declined.

\- \*\*Emergencies short-circuit everything.\*\* A fall, chest pain or breathlessness triggers an immediate "call 112" and an urgent alert to every family member.

\- \*\*Fast.\*\* All tool logic is local and deterministic, with no LLM inside the server. Measured over a public tunnel, the slowest tool call was \*\*205 ms\*\* (the Alexa+ requirement is under 500 ms); locally it was \*\*27 ms\*\*.



\## Run it (Windows, macOS or Linux, Python 3.10+)



```bash

git clone https://github.com/pandeylakshya207-max/saathi-alexa

cd saathi-alexa

python -m venv .venv

\# Windows: .venv\\Scripts\\activate     macOS/Linux: source .venv/bin/activate

pip install -r requirements.txt

python store.py --seed          # loads a realistic demo week for Kamla

```



\*\*1. Start the MCP server\*\* (terminal 1)



```bash

python server.py                # Streamable HTTP at http://127.0.0.1:8000/mcp

```



\*\*2. Play the whole story from the command line\*\* (terminal 2)



```bash

python demo.py                  # or: python demo.py https://<your-public-url>/mcp

```



\*\*3. Simulated Alexa+ devices\*\* (terminal 2): needs a free Groq API key



Create a `.env` file:



```

GROQ\_API\_KEY=your\_key

GROQ\_MODEL=openai/gpt-oss-20b

SAATHI\_MCP\_URL=http://127.0.0.1:8000/mcp

```



```bash

python alexa\_sim.py             # open http://127.0.0.1:8100 in Chrome

```



Click \*\*Reset demo week\*\*, then talk to the Echo Show and the phone (mic or keyboard).



\*\*4. Give it a public URL\*\* (optional, for a remote MCP client)



```bash

cloudflared tunnel --url http://127.0.0.1:8000 --http-host-header 127.0.0.1:8000

```



The `--http-host-header` flag keeps the MCP SDK's DNS-rebinding protection happy behind the tunnel.



\## Why a simulated Alexa+ experience?



The hackathon allows either a live Alexa+ MCP add-on or a simulated Alexa+ experience. The Saathi \*\*MCP server is real and spec-compliant\*\*. Connecting it to production Alexa+ requires the Alexa AI CLI, which is distributed through a private AWS CodeArtifact registry and needs an AWS account to install. Our team could not create one, so the devices are simulated while every tool call goes to the real server. This is documented in our friction log.



\## Companion open-source project



\[\*\*mcp-voice-kit\*\*](https://github.com/pandeylakshya207-max/mcp-voice-kit): voice-safe text, spoken lists and IDs, voice linting and a latency-budget decorator for MCP servers whose answers are spoken aloud. It was extracted from what we learned building Saathi.



\## Roadmap



\- Live Alexa+ add-on with OAuth 2.1 account linking, so each family has its own Saathi

\- Real booking partners (home lab tests, doctor visits) behind the same approval flow

\- Proactive evening check-ins and a weekly summary for the family

\- More Indian languages



\## License



MIT

