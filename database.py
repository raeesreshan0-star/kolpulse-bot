name: KOLPulse Bot

on:
  workflow_dispatch:
  schedule:
    - cron: "0 */6 * * *"

concurrency:
  group: kolpulse-bot
  cancel-in-progress: false

permissions:
  contents: read
  actions: read

jobs:
  run-bot:
    runs-on: ubuntu-latest
    timeout-minutes: 345

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      # IMPORTANT:
      # Restore the database from known-good workflow run #880.
      # This is intentionally NOT "latest successful", because newer
      # runs may contain the empty/fresh database that caused data loss.
      - name: Recover old KOLPulse database from run #880
        uses: dawidd6/action-download-artifact@v25
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          workflow: bot.yml
          run_number: 880
          name: kolpulse-db
          path: .
          if_no_artifact_found: fail

      - name: Verify recovered database
        shell: bash
        run: |
          if [ ! -f kolpulse.db ]; then
            echo "ERROR: kolpulse.db was not recovered."
            exit 1
          fi

          echo "Recovered database:"
          ls -lh kolpulse.db

          echo "Database tables:"
          sqlite3 kolpulse.db ".tables"

          echo "Verified channels:"
          sqlite3 kolpulse.db "SELECT COUNT(*) FROM verified_channels;"

          echo "Saved calls:"
          sqlite3 kolpulse.db "SELECT COUNT(*) FROM calls;"

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: python -m pip install -r requirements.txt

      - name: Run KOLPulse Bot
        continue-on-error: true
        env:
          BOT_TOKEN: ${{ secrets.BOT_TOKEN }}
          GROUP_CHAT_ID: ${{ secrets.GROUP_CHAT_ID }}
          OWNER_USER_ID: ${{ secrets.OWNER_USER_ID }}
          PROMOTIONAL_VIDEO_FILE_ID: ${{ secrets.PROMOTIONAL_VIDEO_FILE_ID }}
          PREMIUM_EMOJI_CALL: ${{ secrets.PREMIUM_EMOJI_CALL }}
          PREMIUM_EMOJI_PLANE: ${{ secrets.PREMIUM_EMOJI_PLANE }}
          PREMIUM_EMOJI_CONTRACT: ${{ secrets.PREMIUM_EMOJI_CONTRACT }}
          PREMIUM_EMOJI_KOL: ${{ secrets.PREMIUM_EMOJI_KOL }}
          PREMIUM_EMOJI_BOT: ${{ secrets.PREMIUM_EMOJI_BOT }}
          PYTHONUNBUFFERED: "1"
        shell: bash
        run: |
          timeout --signal=SIGTERM --kill-after=30s 19200s python -u bot.py
          status=$?
          if [ "$status" -eq 124 ]; then
            echo "Planned 5h20m runtime reached."
            exit 0
          fi
          exit "$status"

      - name: Save KOLPulse database
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: kolpulse-db
          path: kolpulse.db
          if-no-files-found: fail
          retention-days: 90
