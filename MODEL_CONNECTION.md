# Model Connection and Detection Boundary

## What Runs Without a Model API

The browser runs the bundled MediaPipe pose model to estimate 33 image/world
landmarks. The backend runs validation, Kalman filtering, HMM/rule recognition,
exercise counting, reduced skeleton fitting, URDF parsing, local evidence gates
and completed-set replay. These components do not call a language model API.

The pose model is a learned model running locally. The current action classifier
combines HMM and engineering rules; it is not a language-model Agent deciding the
action on every frame. The URDF parser performs structural parsing, not AI inference.

Without configuration, actual A model review and B expert generation are disabled.
Mock model integration tests do not substitute for evaluating actual model output.

## Required API

`coach/app/model_client.py` implements this contract:

- POST `{base_url}/chat/completions` with `Authorization: Bearer {api_key}`.
- Request fields: `model`, `messages`, and optionally
  `response_format: {"type":"json_object"}` when `json_mode=true`.
- Non-streaming response: `choices[0].message.content` must be text containing JSON.
- A/B applications validate the returned JSON and evidence limits themselves.
- Chinese comprehension, reliable instruction following and sufficient context for
  the Skill, selected knowledge records and compact JSON are needed.

An OpenAI-compatible endpoint is sufficient if it implements these fields and
response shapes. Native vendor function calling is not required: A's bounded tool
choices are application-validated JSON. Embeddings are not required by the current
local knowledge retrieval implementation. Video/image input is not required on
this route; the API receives measured evidence, not raw video.

If a future route asks a model to inspect RGB/video directly, that route needs a
multimodal model and additional evaluation. A stronger text model cannot repair
incorrect landmark measurements automatically.

## Configuration

Edit `coach/config.json`, using `coach/config.example.json` as the field reference:

```json
{
  "api_key": "",
  "base_url": "https://api.openai.com/v1",
  "model": "gpt-4.1-mini",
  "timeout_seconds": 90,
  "json_mode": true
}
```

`gpt-4.1-mini` is the repository's configured default, not a claim about today's
best model or account availability. Use an exact model ID available at the chosen
provider. `base_url` is the prefix before `/chat/completions`; do not put the full
completion path in it. HTTPS is required for remote endpoints. Local endpoints
may use HTTP on localhost/127.0.0.1.

Environment overrides: `FITNESS_API_KEY`, `FITNESS_BASE_URL`, `FITNESS_MODEL`.
Keys remain on the backend; the UI receives only configuration status. If a
provider lacks JSON mode, `json_mode=false` omits that request field, but the model
still has to return valid JSON matching the application's contracts.

In the webpage, finish a set. With configuration, it requests A evidence review
then the corresponding B specialist. Without configuration, it produces the local
set result. Reports/plans use the same client and configuration.

No actual API key was present during this verification. Official OpenAI documentation
fetches returned HTTP 403 in this environment; current model availability and pricing
were not verified. The interface requirements above come from the inspected local
implementation. Actual provider compatibility and expert-output quality need a
real connection test after configuration.
