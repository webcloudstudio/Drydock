<!-- Compacted from Rigging/stack/alexa-skills-kit.md sha256=4c695c8070add726dcce7a00893a7cd865bd7468c9f1df3532d01536c83a7d16 on 2026-09-20 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# Alexa Skills Kit (ASK) Best Practices — Contract Surface

### Rule: skill-type

Use a Custom Skill for conversational voice commands.

### Rule: intent-model

Use a minimal intent model with one catch-all intent containing an `AMAZON.SearchQuery` free-text slot.

Constraints: Do not use `AMAZON.AlphaNumeric` for free-text phrases.

### Rule: production-endpoint

Configure the production skill endpoint with a Lambda ARN.

Constraints: Use ngrok only for local development testing.

### ALEXA_SKILL_ID

Configure `ALEXA_SKILL_ID` with the expected Alexa application ID.

Constraints: Validate the request application ID against `ALEXA_SKILL_ID`.

### Rule: request-validation

Validate the Alexa application ID for Lambda requests; validate the Alexa certificate for HTTPS endpoints.

### Rule: session-types

Handle `LaunchRequest`, `IntentRequest`, and `SessionEndedRequest` request types.

Constraints: Set `shouldEndSession` appropriately and use session attributes for multi-turn conversations.

### Rule: voice-response

Build responses using `outputSpeech`, `reprompt`, `shouldEndSession`, and `card`.

Constraints: Support `PlainText` and `SSML` output speech, reprompts for open sessions, and `SimpleCard` or `StandardCard` cards.

### Rule: certification

Include `StopIntent`, `CancelIntent`, and `HelpIntent`, configure a privacy policy URL, select a category, and complete submission testing.

### Rule: lambda-permission

Grant `lambda:InvokeFunction` permission to `alexa-appkit.amazon.com`.

### Rule: developer-testing

Test the skill with the Alexa Developer Console simulator, including raw `IntentRequest` JSON input before physical-device testing.
