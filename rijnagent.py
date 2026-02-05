name: Rijnagent – Telegram (Production)

on:
  schedule:
    - cron: "5 * * * *"      # elk uur om XX:05 UTC
  workflow_dispatch:

permissions:
  contents: read

jobs:
  run:
    runs-on: ubuntu-latest

    env:
      TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
      TELEGRAM_CHAT_ID:   ${{ secrets.TELEGRAM_CHAT_ID }}
      SEND_PHOTOS: "true"
      LOW_LINE_CM: "200"
      MPLBACKEND: Agg

    steps:
      - uses: actions/checkout@v4

      - name: Install Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: |
          pip install requests matplotlib numpy

      - name: Run Rijnagent
        run: python rijnagent.py
