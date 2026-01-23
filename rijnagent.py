
name: Rijn Waterstanden Agent (TEST)

on:
  schedule:
    # TEST: elke 7 minuten om te bewijzen dat 'schedule' triggert
    - cron: "*/7 * * * *"
  workflow_dispatch:

jobs:
  run-agent:
    runs-on: ubuntu-latest

    steps:
      # PROOF: log waardoor deze run is gestart
      - name: PROOF - is dit een scheduled run?
        run: echo "Triggered by: $GITHUB_EVENT_NAME at $(date -u +'%Y-%m-%dT%H:%M:%SZ')"

      # 1) Hoofdrepo uitchecken
      - name: Checkout hoofd-repo
        uses: actions/checkout@v4

      # 2) Python en dependencies
      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Installeer dependencies
        run: |
          python -m pip install --upgrade pip
          pip install requests twilio matplotlib

      # 3) Debug voor script
      - name: Debug voor script
        shell: bash
        run: |
          echo "PWD="; pwd
          echo "--- ls -la . ---"; ls -la .
          echo "--- ls -la graphs (verwacht: bestaat nog niet) ---"
          ls -la graphs || true

      # 4) Draai agent (maakt tekst + PNG's)
      - name: Agent uitvoeren (tekst en grafieken genereren)
        env:
          TWILIO_SID: ${{ secrets.TWILIO_SID }}
          TWILIO_AUTH: ${{ secrets.TWILIO_AUTH }}
        run: |
          python rijnagent.py

      # 5) Debug na script
      - name: Debug na script
        shell: bash
        run: |
          echo "--- ls -la graphs (verwacht: nu .png's) ---"
          ls -la graphs || true

      # 6) Media-repo uitchecken (PUBLIC) op branch main - met PAT: MEDIA_TOKEN
      - name: Checkout media-repo
        uses: actions/checkout@v4
        with:
          repository: Christiaan1984/rijnagent-media
          ref: main
          token: ${{ secrets.MEDIA_TOKEN }}
          path: media

      # (Optioneel) init-fallback: alleen als media-repo leeg is
      - name: Initialiseer media-repo als leeg (optioneel, safe)
        working-directory: media
        shell: bash
        run: |
          set -e
          if ! git rev-parse --verify HEAD >/dev/null 2>&1; then
            echo "# Rijnagent media" > README.md
            git config user.name  "github-actions"
            git config user.email "github-actions@github.com"
            git add README.md
            git commit -m "init media repo"
            git push -u origin main
            echo "Media-repo geinitialiseerd."
          else
            echo "Media-repo heeft al commits."
          fi

      # 7) Kopieer PNG's (safe)
      - name: Kopieer grafieken naar media-repo (safe)
        shell: bash
        run: |
          set -e
          if [ -d "graphs" ]; then
            if ls graphs/*.png >/dev/null 2>&1; then
              cp graphs/*.png media/
              echo "PNG-grafieken gekopieerd naar ./media"
            else
              echo "Map graphs bestaat, maar geen PNG-bestanden gevonden."
            fi
          else
            echo "Map graphs bestaat niet."
          fi

      # 8) Commit en push (safe)
      - name: Commit en push grafieken (safe)
        working-directory: media
        shell: bash
        run: |
          set -e
          git config user.name  "github-actions"
          git config user.email "github-actions@github.com"

          if ls *.png >/dev/null 2>&1; then
            git add *.png
            if ! git diff --cached --quiet; then
              git commit -m "Update grafieken $(date -u +'%Y-%m-%dT%H:%M:%SZ')"
              git push
              echo "Grafieken gecommit en gepusht"
            else
              echo "Geen wijzigingen om te committen."
            fi
          else
            echo "Geen .png-bestanden in ./media — commit overgeslagen."
          fi

      # 9) Verstuur grafieken via WhatsApp (1 media per bericht)
      - name: Verstuur grafieken via WhatsApp
        env:
          TWILIO_SID: ${{ secrets.TWILIO_SID }}
          TWILIO_AUTH: ${{ secrets.TWILIO_AUTH }}
          FROM: "whatsapp:+14155238886"
          TO: "whatsapp:+31646260683"
          BASE: "https://raw.githubusercontent.com/Christiaan1984/rijnagent-media/main"
        shell: bash
        run: |
          send_media () {
            label="$1"
            file="$2"
            url="${BASE}/${file}"
            if curl -s --head "$url" | head -n 1 | grep "200" >/dev/null; then
              code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "https://api.twilio.com/2010-04-01/Accounts/${TWILIO_SID}/Messages.json" \
                -u "${TWILIO_SID}:${TWILIO_AUTH}" \
                --data-urlencode "From=${FROM}" \
                --data-urlencode "To=${TO}" \
                --data-urlencode "Body=${label} - laatste 48 uur" \
                --data-urlencode "MediaUrl=${url}")
              echo "${label}: HTTP ${code}"
            else
              echo "${label}: nog geen publieke URL gevonden op ${url}"
            fi
          }

          send_media "BONN"        "bonn_48u.png"
          send_media "KOELN"       "koeln_48u.png"
          send_media "DUESSELDORF" "duesseldorf_48u.png"
