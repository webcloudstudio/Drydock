<!-- Compacted from Rigging/stack/alexa-skills-kit.md sha256=7b33570729ed514683ea54fcede66d39d1da2afc19f68404c1c07b2e7f8d4678 on 2026-10-24 by drydock rigging compact — regenerate with: drydock rigging compact --include-file {rel_source} -->

# Alexa Skills Kit (ASK) Best Practices — Contract Surface

## Interaction Model

### Rule: free-text-intent-slot

Use a minimal intent model with one catch-all intent and an `AMAZON.SearchQuery` free-text slot.

Constraints: Do not use `AMAZON.AlphaNumeric` for free-text phrases.

## Endpoint Configuration

### config_key `Lambda ARN`

Configure the production skill endpoint as a Lambda ARN.

Constraints: Use ngrok only for local development testing.

## Request Validation

### config_key `ALEXA_SKILL_ID`

Configure the expected Alexa application ID used to validate incoming requests.

Constraints: Validate the request `applicationId` against `ALEXA_SKILL_ID`.

## Session Management

### Rule: request-types

Handle `LaunchRequest`, `IntentRequest`, and `SessionEndedRequest`.

Constraints: Support `shouldEndSession` and session attributes for multi-turn conversations.

## Voice Responses

### Rule: response-shape

Return Alexa responses containing `outputSpeech`, with optional `reprompt`, `shouldEndSession`, and `card`.

Constraints: Support `PlainText` and `SSML` output speech; use `SimpleCard` or `StandardCard` cards.

## Certification

### Rule: required-intents

Include `StopIntent`, `CancelIntent`, and `HelpIntent`.

Constraints: Configure a privacy policy URL and test with the Alexa Developer Console simulator, including raw `IntentRequest` JSON input.

## Lambda Permissions

### Rule: invoke-permission

Grant `lambda:InvokeFunction` permission to `alexa-appkit.amazon.com`.
