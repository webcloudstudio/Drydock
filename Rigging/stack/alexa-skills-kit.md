# Alexa Skills Kit (ASK) Best Practices

**Version:** 20260320 V1  
**Description:** Alexa Skills Kit patterns: intent handlers, slots, and response builders

Technology reference for building Alexa Custom Skills with Lambda endpoints.
This file does not change between projects.

Prerequisites: `stack/aws-lambda.md`

---

## 1. Skill Types

**Rule**: TODO — Document Custom Skill vs. Smart Home Skill vs. Flash Briefing.
Custom Skill is the correct choice for conversational voice commands.

**Why**: TODO

---

## 2. Interaction Model: Intents and Slots

**Rule**: Use a minimal intent model. Prefer one catch-all intent with a
`AMAZON.SearchQuery` free-text slot over multiple intents per keyword.
Multiple intents require model redeployment for every new keyword; a single
free-text intent delegates routing to application code.

```json
// TODO: Add full interaction model JSON template
// Key choice: AMAZON.SearchQuery captures multi-word natural language phrases.
// AMAZON.AlphaNumeric truncates at word boundaries — do not use.
```

**Why**: TODO — Extensibility: routing rules in a database can be changed
without Alexa model redeployment.

---

## 3. Request/Response JSON Format

**Rule**: TODO — Document the Alexa IntentRequest JSON structure:
session, context, request objects. Document the required response format:
outputSpeech, reprompt, shouldEndSession, card.

```json
// TODO: Add request schema
// TODO: Add response schema
```

**Why**: TODO

---

## 4. Skill Endpoint: Lambda ARN vs. HTTPS

**Rule**: Use Lambda ARN as the endpoint for production. Use ngrok for
local development testing only.

```
// TODO: Document how to configure Lambda ARN endpoint in developer console
// TODO: Document ngrok local testing workflow
```

**Why**: Lambda ARN requires no infrastructure (no HTTPS cert, no public IP).
ngrok is ephemeral and unsuitable for production.

---

## 5. Request Signature Verification

**Rule**: TODO — Document validation of the applicationId from the request
against the expected ALEXA_SKILL_ID env var. Document the full Alexa
certificate validation process (for HTTPS endpoints only; Lambda endpoints
are verified by AWS automatically).

```python
# TODO: Add skill ID validation code
```

**Why**: TODO — Prevents unauthorized callers from invoking the Lambda function
if the ARN is discovered.

---

## 6. Session Management

**Rule**: TODO — Document LaunchRequest (session start), IntentRequest
(during session), SessionEndedRequest (session close). Document shouldEndSession
flag and session attributes for multi-turn conversations.

**Why**: TODO

---

## 7. Voice Response Builder

**Rule**: TODO — Document outputSpeech types (PlainText vs. SSML),
reprompt (for keeping session open), and card types (SimpleCard, StandardCard).

```python
# TODO: Add response builder helper
```

**Why**: TODO

---

## 8. Developer Console Testing

**Rule**: TODO — Document the Alexa Developer Console skill simulator for
testing without a physical device. Document the JSON input tab for sending
raw IntentRequest events.

**Why**: TODO

---

## 9. Certification Requirements

**Rule**: TODO — Document required intents (Stop, Cancel, Help), privacy
policy URL requirement, category selection, and testing checklist for submission.

**Why**: TODO

---

## Summary Checklist

- [ ] TODO: AMAZON.SearchQuery used for free-text utterance slots
- [ ] TODO: Required intents included: StopIntent, CancelIntent, HelpIntent
- [ ] TODO: Skill ID validated in Lambda handler
- [ ] TODO: Lambda endpoint configured (not HTTPS)
- [ ] TODO: lambda:InvokeFunction permission granted to alexa-appkit.amazon.com
- [ ] TODO: shouldEndSession set correctly per intent
- [ ] TODO: Tested with developer console simulator before physical device
- [ ] TODO: Privacy policy URL set (required for certification)
