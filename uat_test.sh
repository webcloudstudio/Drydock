#                       Claude  Codex
# CommonMark            Y
drydock uat resume CommonMark --run 20261025.023211 --repair-attempts 21 --model luna
drydock uat jq --model luna
drydock uat fxrates --model luna

drydock uat fxrates --model luna

drydock uat CsvStat --model claude-haiku-5-5 --plan-override-model sonnet
drydock uat DrydockStats --model claude-haiku-5-5 --plan-override-model sonnet
drydock uat DupFind --model claude-haiku-5-5 --plan-override-model sonnet
drydock uat FxRates --model claude-haiku-5-5 --plan-override-model sonnet
drydock uat LayersTesting --model claude-haiku-5-5 --plan-override-model sonnet
drydock uat jq --model claude-haiku-5-5 --plan-override-model sonnet
