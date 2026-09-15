#!/usr/bin/env bash
#
# Capture a browser profile from a headless remote desktop, without a GUI.
#
# Firefox and Chromium use completely different mechanisms, so both are implemented here rather
# than pretending one flag set fits both:
#   firefox  -- MOZ_PROFILER_* env vars to START recording; --finish sends SIGUSR2, which makes
#               Gecko DUMP THE PROFILE AND STOP, leaving the browser running. "--finish has to
#               end the browser. There is no way around that." is what this header used to say,
#               and it was WRONG: it cost a live game session and its save file before anyone
#               read tools/profiler/core/platform.cpp, where SIGUSR1/SIGUSR2 are documented in a
#               comment block and profiler_dump_and_stop() is the handler. Verified present in
#               the installed libxul (Firefox 155.0.1), not assumed from upstream source.
#   chromium -- startup tracing with a FIXED DURATION set at launch. MEASURED on this build:
#               only the duration expiring writes the file -- SIGTERM produces nothing at all.
#               --finish therefore never signals Chromium; it waits for the window to close.
# Both land as JSON. The Firefox Profiler imports Chrome traces
# (src/profile-logic/import/chrome.ts), so one tool can read either.
#
# Why this is a script and not a few ssh commands: the ad-hoc version was attempted twice and
# failed twice, in ways that were cheap to make and expensive to notice.
#
#   1. It was started with MOZ_PROFILER_STARTUP_FEATURES=js,stackwalk,cpu. There is no 'cpu'
#      feature. Firefox printed its help text and ran for minutes recording nothing, and the
#      only trace was one line buried in a 214-line log.
#   2. It was "finished" by killing Firefox in a way that produced no dump at all. The log
#      showed 'Exiting due to channel error' nine times, no JSON was written, and that was
#      reported as though it had worked.
#
# Both are designed out below rather than left as things to remember. --start validates the
# variable NAMES against the installed libxul and the feature VALUES against Firefox's own
# MOZ_PROFILER_HELP table -- the second matters because 'cpu' was a bad value, not a bad name,
# and grepping libxul cannot catch it ('cpu' is a substring of 'cpuallthreads'). It then aborts
# if the launch was rejected anyway. --finish treats a parseable file as the only definition of
# success, because the previous attempt reported success while producing no file at all.
#
# A third failure is guarded too, and the guard had to be made ABSOLUTE after it failed twice.
#
#   SIGTERM TO A BROWSER IS NOT A CLEAN CLOSE FOR THE PAGE INSIDE IT.
#
# The browser exits, but the web app never runs its unload path, so anything it persists on a
# clean close -- localStorage, IndexedDB, a save slot -- is left half-written. For the game this
# host exists to run, that means it will not start again afterwards. Losing the profile run is
# cheap; losing the save is not, and it is not recoverable from here.
#
# History, because this is the part that matters: the first version killed a running Firefox
# with no warning and destroyed a live game session. The fix was to refuse unless
# --replace-running was passed. On 2026-09-13 the operator passed --replace-running against a
# Firefox with the game loaded and destroyed the save again. A warning plus an opt-out flag is
# not a guard -- it is a speed bump in front of the exact mistake it was written for.
#
# So the flag is GONE. There is no way to make this script stop a running browser. If one is
# running, it refuses and tells you to close it from inside the session, where the page gets its
# unload event. That is structural: the footgun is absent, not discouraged.
#
# THREE MORE FAILURES, diagnosed 2026-09-12, fixed here:
#
#   3. SIGTERM went to the whole process tree. 'pkill -f firefox' matches the parent AND every
#      content child. The children died out from under the parent, which is exactly the
#      'Exiting due to channel error' x9 above, and the orderly shutdown never reached the dump.
#      Firefox on Linux DOES shut down normally on SIGTERM -- bug 1837907, landed in Firefox
#      122 -- so the signal was right and the recipients were wrong. Everything below signals
#      the PARENT ONLY: content processes carry -contentproc (Firefox) or --type= (Chromium).
#
#   4. Chromium's trace file was created and stayed 0 bytes. This is documented behaviour, not
#      a mystery. components/tracing/common/tracing_switches.cc, on --trace-startup-duration:
#      "Sets the time in seconds until startup tracing ends. If omitted: if --trace-startup is
#      specified, a default of 5 seconds is used; if --enable-tracing is specified, tracing
#      lasts until the browser is closed." This script used to omit the duration and then KILL
#      the browser. Killed is not closed: the file is created at start and finalised at stop.
#      Now a duration is always passed, the trace finalises on its own, and --finish never
#      signals Chromium at all. Closing it early was tried on 2026-09-13 and produced NO FILE,
#      so the window really is fixed at launch: keep --duration short and start it when the
#      session is ready.
#
#   5. Validating Chromium flags by grepping the binary proved nothing. --trace-startup* are
#      legacy strings that still exist in the binary while the flags do nothing, which is how
#      attempt 2 passed validation and captured nothing. The grep is kept only as a
#      does-this-build-predate-the-flag check and is labelled as such; the real control is
#      --selftest below, which records a throwaway 10-second trace before the real run and
#      fails if no parseable file appears. Without it, --start would again be asserting that
#      unverified flags work.
#
# Usage:
#   scripts/vdesktop-01/browser-profile.sh <host> --start [--engine firefox|chromium]
#                                      [--duration SECONDS]
#                                      [--user NAME] [--display :N] [--url URL] [--out PATH]
#
#   --start REFUSES if a browser is already running. Close it from inside the session first
#   (Moonlight/VNC), so the page can flush its state. There is deliberately no override.
#   scripts/vdesktop-01/browser-profile.sh <host> --finish [--engine firefox|chromium] [--dumpdir DIR]
#
#   firefox --finish sends SIGUSR2: it DUMPS THE PROFILE AND LEAVES FIREFOX RUNNING.
#   It never closes the browser. Nothing open in the session is at risk.
#   scripts/vdesktop-01/browser-profile.sh <host> --selftest --engine chromium
#
#   scripts/vdesktop-01/browser-profile.sh vdesktop-01 --start --engine chromium --duration 120
#   ... reload the save and get into the interesting state before the window closes ...
#   scripts/vdesktop-01/browser-profile.sh vdesktop-01 --finish --engine chromium
#
# Then read the JSON locally. Safe to re-run; --start on an idle host is harmless.

set -euo pipefail

ENGINE=firefox
URL=""
DESKTOP_USER=andy
DISPLAY_NUM=":0"
OUT=""            # defaulted per-engine below
DUMPDIR=""        # where SIGUSR2 writes; defaulted from the desktop user below
WAYLAND_SOCK=""   # --wayland <name>: run the browser as a NATIVE WAYLAND CLIENT, not on X11
LIBXUL=/usr/lib/firefox/libxul.so

# Sampling interval in ms. 2 is a compromise: finer costs CPU on a box that is already the
# thing under test, and the profiler's own SamplerThread was measured at 53% of a core here.
INTERVAL=2

# MOZ_PROFILER_STARTUP_ENTRIES has a documented floor of 16777216; smaller values are refused
# outright. At 8 bytes per entry that is ~128 MB of circular buffer, which is also why a long
# recording simply keeps the most recent portion rather than growing without bound.
ENTRIES=16777216

# 'cpuallthreads' and NOT 'cpu'. See the header. 'js' and 'stackwalk' are defaults but are
# named explicitly so a future default change cannot silently drop them.
FEATURES=js,stackwalk,cpuallthreads

# Chromium trace categories. blink covers script and style, cc and viz the compositor, gpu the
# (absent) GPU path, toplevel the task scheduler. The last two are what answer the question
# this whole exercise exists for: v8.execute is JS execution, and
# disabled-by-default-devtools.timeline is what makes the DevTools-style
# Scripting/Rendering/Painting split reconstructable without symbolication.
CATEGORIES="blink,cc,gpu,viz,toplevel,sequence_manager,v8.execute,disabled-by-default-devtools.timeline"

# Chromium only, and it is THE mechanism, not a cap: the window starts at launch and cannot be
# ended early, so the workload must be in the state you want captured when it closes. Short by
# default for that reason -- long windows mean long waits with nothing to show if the moment
# is missed. Only the last BUFKB of events survive anyway.
DURATION=120

# Ring buffer size, in KB. NOT a default carried over from anywhere: the self-test measured
# ~21 MB of trace in 10 SECONDS on about:blank with these categories, so a 300s window would
# be ~600 MB unbounded -- and --finish parses the result with json.load on a container with
# 4 GB total. 50 MB keeps the last ~25s of the session, which is what record-continuously is
# for, and parses without threatening the box that is itself under test.
BUFKB=51200

usage() {
  # The Usage block in the header, extracted by content rather than by line number so that
  # editing the comments above it cannot silently make this print the wrong thing.
  sed -n '/^# Usage:/,/^$/p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
}

HOST=""
MODE=""
DURATION_SET=0

while [ $# -gt 0 ]; do
  case "$1" in
    --engine)          ENGINE="$2"; shift ;;
    --url)             URL="$2"; shift ;;
    --start)           MODE=start ;;
    --finish)          MODE=finish ;;
    --selftest)        MODE=selftest ;;
    --duration)        DURATION="$2"; DURATION_SET=1; shift ;;
    --user)            DESKTOP_USER="$2"; shift ;;
    --display)         DISPLAY_NUM="$2"; shift ;;
    --out)             OUT="$2"; shift ;;
    --dumpdir)         DUMPDIR="$2"; shift ;;
    --wayland)         WAYLAND_SOCK="$2"; shift ;;
    -h|--help)         usage ;;
    -*)                echo "unknown option: $1" >&2; usage ;;
    *)                 [ -n "$HOST" ] && { echo "unexpected argument: $1" >&2; usage; }
                       HOST="$1" ;;
  esac
  shift
done

[ -n "$HOST" ] || { echo "error: no host given" >&2; usage; }
[ -n "$MODE" ] || { echo "error: pass --start, --finish or --selftest" >&2; usage; }

# $OUT is the CHROMIUM trace path, and for firefox it is only the MOZ_PROFILER_SHUTDOWN path --
# which needs an orderly quit and is NOT how firefox --finish works any more. The firefox dump
# location is chosen by Gecko and cannot be overridden: $DUMPDIR/profile_<processtype>_<pid>.json.
#
# /var/tmp, NEVER /tmp. MEASURED on vdesktop-01 2026-09-14: /tmp is tmpfs ADVERTISING 31.3G on a
# container that has 4096 MB of RAM and 512 MB of swap -- LXC sizes that tmpfs from the HOST's
# memory, so `df` reports 31G free and there is no guard of any kind. A chromium trace of this
# game runs ~10 MB per second of wall clock (626 MB / 60.5 s, measured), so a 240 s window is
# ~2.5 GB held in RAM on a 4 GB box. /var/tmp is on the rootfs (rbd0, 27 G free) and is 1777, so
# the desktop user can write it directly.
case "$ENGINE" in
  firefox)  BROWSER=/usr/bin/firefox;  : "${OUT:=/var/tmp/ffprofile.json}" ;;
  chromium) BROWSER=/usr/bin/chromium; : "${OUT:=/var/tmp/chromium-trace.json}" ;;
  *) echo "error: --engine must be firefox or chromium (got '$ENGINE')" >&2; exit 2 ;;
esac
LOG=/tmp/browser-profile-$ENGINE.log
# Set after --user is parsed, and before either remote block is generated: Gecko writes the
# SIGUSR2 dump into the desktop user's download directory.
: "${DUMPDIR:=/home/$DESKTOP_USER/Downloads}"
DEADLINE=/tmp/browser-profile-$ENGINE.deadline
TRACECFG=/tmp/browser-profile-trace-config.json

case "$DURATION" in
  ''|*[!0-9]*) echo "error: --duration must be a whole number of seconds" >&2; exit 2 ;;
esac
[ "$DURATION_SET" = 0 ] || [ "$ENGINE" = chromium ] || {
  echo "error: --duration is Chromium-only. Firefox records until --finish closes it." >&2
  exit 2; }
[ "$MODE" != selftest ] || [ "$ENGINE" = chromium ] || {
  echo "error: --selftest is a Chromium control; Firefox needs no unproven flags" >&2; exit 2; }

# Everything below runs on the remote host. Scripts are fed over stdin rather than embedded in
# an ssh argument so that quoting is never in play -- the local shell may be fish, which
# mangles heredocs and $? differently from bash.
remote() { ssh -o BatchMode=yes -o ConnectTimeout=15 "$HOST" 'bash -s' ; }

# Shared remote prelude. Defined once so --start, --finish and --selftest cannot drift apart in
# how they identify a browser parent -- which is the bug in note 3.
prelude() {
  cat <<'PRE'
fail() { echo "FAILED: $*" >&2; exit 1; }

# Match the ENGINE NAME, not the wrapper path. /usr/bin/chromium and /usr/bin/firefox are
# shell wrappers that exec /usr/lib/<engine>/<engine>, so pgrep -f on the wrapper path finds
# nothing and the already-running guard silently fails open -- which it did, and it launched
# over a live session.
browser_pids() { pgrep -u "$USER_NAME" -f "$ENGINE" 2>/dev/null || true; }

# The PARENT processes only. Signalling the whole tree kills content children out from under
# the parent, the orderly shutdown never completes and no profile is written -- note 3 in the
# header. Firefox content processes carry -contentproc; Chromium's carry --type=.
browser_parents() {
  local marker p cmd
  case "$ENGINE" in
    firefox)  marker='-contentproc' ;;
    chromium) marker='--type=' ;;
    *) fail "browser_parents: unknown engine $ENGINE" ;;
  esac
  for p in $(browser_pids); do
    cmd=$(sudo cat "/proc/$p/cmdline" 2>/dev/null | tr '\0' ' ') || true
    [ -n "$cmd" ] || continue
    case "$cmd" in
      *"$marker"*) ;;
      *) echo "$p" ;;
    esac
  done
}
PRE
}

# ---------------------------------------------------------------------------- selftest
# A positive control for the Chromium trace flags. Records 10 seconds on about:blank in a
# throwaway profile directory, lets the duration expire WITHOUT signalling anything, and fails
# unless a parseable trace appears. This is the only thing that distinguishes "the flags are
# accepted" from "the flags work" -- attempt 2 had the former and captured nothing.
selftest_block() {
  cat <<SELFTEST
echo "== Chromium trace self-test (positive control) =="
ST_DIR=\$(mktemp -d /tmp/browser-profile-selftest-XXXXXX)
ST_OUT="\$ST_DIR/trace.json"
# Two different users write into this directory: the log redirect below is performed by THIS
# shell (whoever ssh'd in), while the trace file and the profile are written by the browser
# running as \$USER_NAME. Both need write access. chown-ing it to \$USER_NAME takes it away
# from the shell doing the redirect, which is a "Permission denied" that then looks exactly
# like the trace flags having failed. It is a throwaway, named at random, removed below.
sudo chmod 0777 "\$ST_DIR"
# --user-data-dir is a throwaway so the real profile is untouched; it doubles as a pkill
# pattern that CANNOT match the browser the user is playing in.
sudo -u "\$USER_NAME" setsid env \
  "\$DISPVAR" \
  XDG_RUNTIME_DIR="/run/user/\$(id -u "\$USER_NAME")" \
  DBUS_SESSION_BUS_ADDRESS="\$DBUS_ADDR" \
  "\$BROWSER" \$OZONE --no-first-run --no-default-browser-check --password-store=basic \
    --user-data-dir="\$ST_DIR/profile" \
    --trace-config-file="\$TRACECFG" \
    --enable-tracing="\$CATEGORIES" --enable-tracing-format=json \
    --enable-tracing-output="\$ST_OUT" --trace-startup-duration=10 \
    about:blank >"\$ST_DIR/log" 2>&1 </dev/null &
sleep 3
pgrep -f "\$ST_DIR/profile" >/dev/null 2>&1 \
  || fail "the self-test browser never started, so this says NOTHING about the trace flags.
       Log: \$ST_DIR/log
\$(tail -20 "\$ST_DIR/log" 2>/dev/null || echo '       (no log was written either)')"
for _ in \$(seq 1 20); do
  sleep 2
  [ -s "\$ST_OUT" ] && break
done
ST_SIZE=\$(stat -c %s "\$ST_OUT" 2>/dev/null || echo 0)
sudo pkill -TERM -f "\$ST_DIR/profile" 2>/dev/null || true
for _ in \$(seq 1 15); do
  pgrep -f "\$ST_DIR/profile" >/dev/null 2>&1 || break
  sleep 1
done
if [ "\$ST_SIZE" = "0" ]; then
  echo "--- self-test browser log ---" >&2
  tail -20 "\$ST_DIR/log" >&2 2>/dev/null || true
  fail "the browser started but the trace flags produced no data in 10s on this build.
       Nothing was recorded, so a real run would waste a game session.
       Left in place for inspection: \$ST_DIR
       Most likely: --enable-tracing-format=json is gone (JSON output is on an upstream
       deprecation path) -- try proto and read it in Perfetto UI, or the
       --trace-config-file/--enable-tracing combination conflicts on this build."
fi
ST_FIRST=\$(sudo head -c 1 "\$ST_OUT") \
  || fail "could not read \$ST_OUT (\$ST_SIZE bytes). The trace exists; this is a permission
       problem in the harness, NOT a verdict on the trace flags."
case "\$ST_FIRST" in
  '['|'{') ;;
  *) fail "self-test trace is \$ST_SIZE bytes but starts with '\$ST_FIRST', not { or [ --
       this build ignored --enable-tracing-format=json and wrote proto.
       Left in place: \$ST_DIR. Read it in Perfetto UI, or pass proto through." ;;
esac
[ "\$ST_SIZE" -lt 104857600 ] || fail "self-test trace is \$ST_SIZE bytes, over the 100 MB
       parse ceiling. Refusing to read it whole -- that is what took the container down on
       2026-09-13. Trim the category list. Left in place: \$ST_DIR"
sudo python3 - "\$ST_OUT" <<'PY' || fail "self-test trace is \$ST_SIZE bytes and starts like JSON
       but does not parse. Left in place: \$ST_DIR"
import collections, json, sys
d = json.load(open(sys.argv[1]))
ev = d.get("traceEvents", []) if isinstance(d, dict) else d
cats = collections.Counter(e.get("cat", "?") for e in ev if isinstance(e, dict))
print("  ok  trace parses as JSON: %d events" % len(ev))
print("      categories present: %s" % ", ".join(
    "%s=%d" % (c, n) for c, n in cats.most_common(8)))
# A disabled-by-default category is never on unless it was asked for, so seeing one proves the
# category list was honoured. about:blank may simply not emit any, hence a note and not a fail
# -- --finish makes this a hard check, where the game is actually running.
if not any("disabled-by-default" in c for c in cats):
    print("      note: no disabled-by-default categories on about:blank; --finish checks this")
PY
echo "  ok  trace flags produce a trace (\$ST_SIZE bytes in 10s)"
echo "  ok  the duration expired on its own -- nothing had to be killed"
sudo rm -rf "\$ST_DIR"
SELFTEST
}

# ---------------------------------------------------------------------------- start / selftest

if [ "$MODE" = start ] || [ "$MODE" = selftest ]; then
  remote <<REMOTE
set -euo pipefail

USER_NAME="$DESKTOP_USER"
DISPLAY_NUM="$DISPLAY_NUM"
WAYLAND_SOCK="$WAYLAND_SOCK"
DUMPDIR="$DUMPDIR"
OUT="$OUT"
LOG="$LOG"
DEADLINE="$DEADLINE"
TRACECFG="$TRACECFG"
BROWSER="$BROWSER"
ENGINE="$ENGINE"
URL="$URL"
LIBXUL="$LIBXUL"
INTERVAL="$INTERVAL"
ENTRIES="$ENTRIES"
FEATURES="$FEATURES"
CATEGORIES="$CATEGORIES"
DURATION="$DURATION"
BUFKB="$BUFKB"
MODE="$MODE"

$(prelude)

[ -x "\$BROWSER" ] || fail "\$BROWSER is not executable on this host"

# --- 1. validate, per engine, against the installed build -----------------------------
if [ "\$ENGINE" = firefox ]; then
  [ -r "\$LIBXUL" ] || fail "\$LIBXUL not readable -- cannot validate profiler options"
  echo "== validating profiler variables against \$LIBXUL =="
  KNOWN=\$(grep -a -o 'MOZ_PROFILER[A-Z_]*' "\$LIBXUL" | sort -u)
  for v in MOZ_PROFILER_STARTUP MOZ_PROFILER_STARTUP_FEATURES MOZ_PROFILER_STARTUP_ENTRIES \
           MOZ_PROFILER_STARTUP_INTERVAL MOZ_PROFILER_SYMBOLICATE MOZ_PROFILER_SHUTDOWN; do
    printf '%s\n' "\$KNOWN" | grep -qx "\$v" \
      || fail "this Firefox build does not accept \$v -- refusing to launch on assumptions"
    echo "  ok  \$v"
  done

  # Feature VALUES, not just names. MOZ_PROFILER_STARTUP_FEATURES=...,cpu once ran for minutes
  # recording nothing: the variable was valid, the value was not. Grepping libxul cannot catch
  # it either, because 'cpu' is a substring of 'cpuallthreads'. Firefox's own help table is
  # authoritative for THIS build and exits immediately with --version.
  echo "== validating profiler features against this build =="
  VALID=\$(timeout 60 env MOZ_PROFILER_HELP=1 "\$BROWSER" --version 2>&1 \
           | grep -oE '^ *[-dDsSx]+ +[0-9]+: "[a-z]+"' | sed -E 's/.*"(.*)"/\1/')
  [ -n "\$VALID" ] || fail "could not enumerate profiler features from \$BROWSER"
  echo "\$FEATURES" | tr ',' '\n' | while read -r f; do
    [ -n "\$f" ] || continue
    if ! printf '%s\n' "\$VALID" | grep -qx "\$f"; then
      printf '%s\n' "\$VALID" | tr '\n' ' ' >&2; echo >&2
      fail "'\$f' is not a profiler feature in this build -- refusing to launch"
    fi
    echo "  ok  feature \$f"
  done || exit 1
else
  # This grep proves the STRING is in the binary and nothing more -- note 5 in the header.
  # --trace-startup* passed exactly this check while doing nothing. It is kept only to catch a
  # build that predates the flag entirely; the self-test below is the actual evidence.
  echo "== checking the trace flag strings exist in \$BROWSER (weak check, see header) =="
  for f in enable-tracing enable-tracing-output enable-tracing-format trace-startup-duration; do
    grep -a -q -o -- "\$f" /usr/lib/chromium/chromium 2>/dev/null \
      || fail "this Chromium build does not know --\$f -- refusing to launch on assumptions"
    echo "  ok  --\$f present in binary (not proof that it works)"
  done
fi

# --- 2. never stop a running browser without saying so -------------------------------
# Only the CHECK happens here. The SIGTERM is deferred to step 5, after the self-test, so that
# an unproven trace setup cannot cost a live session before it is found to be broken -- which
# is the order the last three attempts got wrong. --selftest never stops anything at all: it
# runs a second browser in a throwaway profile directory alongside whatever is already there.
RUNNING=\$(browser_pids)
if [ -n "\$RUNNING" ]; then
  echo
  echo "== \$ENGINE is ALREADY RUNNING as \$USER_NAME =="
  ps -o pid,etime,args -p \$(echo "\$RUNNING" | tr '\n' ',' | sed 's/,\$//') 2>/dev/null | head -4 || true
  if [ "\$MODE" = selftest ]; then
    echo
    echo "  --selftest leaves it alone; the control runs in a throwaway profile directory."
  else
    echo
    fail "refusing to stop it, and there is no flag that will.
       SIGTERM ends the browser WITHOUT running the page's unload path, so a web app's
       save state is left half-written. That destroyed this host's game save twice.
       Close the browser from inside the session -- Moonlight, or VNC on localhost:5900 --
       and let the page shut down properly. Then re-run this command."
  fi
fi

# --- 3. session D-Bus -----------------------------------------------------------------
# Inherit the session's D-Bus. Launching without it gives the browser 13x "Failed to connect to
# the bus", and on this host that breaks Chromium sign-in: it encrypts stored credentials through
# the Secret Service over D-Bus. Firefox has its own password store and does not care, which is
# why only Chromium failed.
#
# ASKED OF THE USER MANAGER, not scraped from a desktop process. This used to read
# /proc/<xfsettingsd>/environ, which returned NOTHING the moment XFCE was removed -- the variable
# silently went empty and the only trace was a one-line warning in a long log. There is no
# desktop shell on this host any more; systemd's user instance is the thing that owns the
# session, so it is the thing to ask.
UID_N=\$(id -u "\$USER_NAME")
DBUS_ADDR=\$(sudo -u "\$USER_NAME" XDG_RUNTIME_DIR="/run/user/\$UID_N" \
             systemctl --user show-environment 2>/dev/null \
             | sed -n 's/^DBUS_SESSION_BUS_ADDRESS=//p')
# Fall back to the well-known socket path. dbus-daemon's user instance always listens here when
# it is socket-activated by the user manager, which it is.
if [ -z "\$DBUS_ADDR" ] && sudo test -S "/run/user/\$UID_N/bus"; then
  DBUS_ADDR="unix:path=/run/user/\$UID_N/bus"
  echo "  note: user manager published no address; using /run/user/\$UID_N/bus"
fi
[ -n "\$DBUS_ADDR" ] || echo "  warn: no session D-Bus found; sign-in may fail" >&2

# --- 3b. which display server, resolved ONCE ------------------------------------------
# Computed here rather than at launch time because the SELF-TEST launches a browser too, and
# it used to hardcode DISPLAY. On a host with no X server the control failed with "Missing X
# server or $DISPLAY" while reporting "the self-test browser never started, so this says
# NOTHING about the trace flags" -- a true statement that hid the real cause.
#
# The socket name is NOT predictable: sway loops wayland-1..wayland-32 and takes the first
# that binds, so any value written down is right until it silently is not. The compositor
# publishes the real one; read it rather than asking anyone to remember it, because a wrong
# name launches a browser that renders nowhere and traces an idle process.
if [ -z "\$WAYLAND_SOCK" ]; then
  ENVFILE="/run/user/\$UID_N/wayland-session.env"
  if sudo test -r "\$ENVFILE"; then
    WAYLAND_SOCK=\$(sudo sed -n 's/^WAYLAND_DISPLAY=//p' "\$ENVFILE" | head -1)
    [ -n "\$WAYLAND_SOCK" ] && echo "  ok  auto-detected WAYLAND_DISPLAY=\$WAYLAND_SOCK"
  fi
fi
if [ -n "\$WAYLAND_SOCK" ]; then
  OZONE="--ozone-platform=wayland"
  DISPVAR="WAYLAND_DISPLAY=\$WAYLAND_SOCK"
else
  if ! sudo test -e "/tmp/.X11-unix/X\${DISPLAY_NUM#:}"; then
    fail "no Wayland socket found and no X server at \$DISPLAY_NUM.
       This host runs a headless WAYLAND compositor; there is no X. Either the compositor is
       not running, or it has not written /run/user/\$UID_N/wayland-session.env yet.
       Check: systemctl --user status sway-headless-wayland.service"
  fi
  OZONE=""
  DISPVAR="DISPLAY=\$DISPLAY_NUM"
fi
echo "  ok  display env: \$DISPVAR \$OZONE"

# --- 4. trace config: keep the END of the window, not the beginning -------------------
# The default record mode fills the buffer and STOPS, so a 300s window would capture the first
# chunk of the session -- loading and signing in -- and not the slow part. record-continuously
# is a ring buffer: it drops the oldest events and keeps the most recent, which is what is
# wanted here. Categories are repeated in both the config file and --enable-tracing so that
# whichever mechanism this build honours, the category set is identical and only record_mode
# can differ. If the config file is ignored entirely, --finish detects it: the trace file will
# have been finalised well before the deadline, and that is reported as a failure rather than
# quietly handing over a trace of the wrong part of the session.
if [ "\$ENGINE" = chromium ]; then
  CATS_JSON=\$(echo "\$CATEGORIES" | tr ',' '\n' | sed 's/.*/"&"/' | paste -sd, -)
  printf '{"trace_config":{"record_mode":"record-continuously","included_categories":[%s],"trace_buffer_size_in_kb":%s}}\n' \
    "\$CATS_JSON" "\$BUFKB" > "\$TRACECFG"
  echo "  ok  trace config written to \$TRACECFG (record-continuously, \${BUFKB}KB ring)"
fi

$(if [ "$ENGINE" = chromium ]; then selftest_block; fi)

if [ "\$MODE" = selftest ]; then
  echo
  echo "SELF-TEST PASSED. The trace flags work on this build."
  exit 0
fi

# --- 5. (removed) ---------------------------------------------------------------------
# This step used to SIGTERM the running browser when --replace-running was given. It is gone,
# along with the flag. Step 2 now refuses unconditionally, so by the time control reaches here
# no browser was running. See the header: SIGTERM is not a clean close for the PAGE, and this
# script destroyed the game's save state twice before that was treated as structural.

# --- 6. launch detached, recording from startup --------------------------------------
sudo rm -f "\$OUT" "\$LOG" "\$DEADLINE"
echo
echo "== launching \$ENGINE with profiling active =="
if [ "\$ENGINE" = firefox ]; then
  # Firefox needs the same treatment: DISPLAY is meaningless here. MOZ_ENABLE_WAYLAND is what
  # makes Gecko pick the Wayland backend rather than falling back to an X connection it cannot
  # make. Left unset on an X host so the variable cannot change behaviour there.
  sudo -u "\$USER_NAME" setsid env \
    "\$DISPVAR" \
    \${WAYLAND_SOCK:+MOZ_ENABLE_WAYLAND=1} \
    XDG_RUNTIME_DIR="/run/user/\$(id -u "\$USER_NAME")" \
    DBUS_SESSION_BUS_ADDRESS="\$DBUS_ADDR" \
    MOZ_PROFILER_STARTUP=1 \
    MOZ_PROFILER_STARTUP_INTERVAL="\$INTERVAL" \
    MOZ_PROFILER_STARTUP_ENTRIES="\$ENTRIES" \
    MOZ_PROFILER_STARTUP_FEATURES="\$FEATURES" \
    MOZ_PROFILER_SYMBOLICATE=1 \
    MOZ_PROFILER_SHUTDOWN="\$OUT" \
    "\$BROWSER" "\$URL" >"\$LOG" 2>&1 </dev/null &
else
  # --trace-startup-duration is the fix for note 4: the trace finalises itself when the window
  # closes and the browser is left alone. The deadline is recorded so --finish can say how long
  # is left, and so it can tell "the ring buffer dropped the early part" (fine) from "tracing
  # stopped early because the buffer filled" (not fine).
  date -d "+\$DURATION seconds" +%s > "\$DEADLINE"
  # --wayland: run as a NATIVE WAYLAND CLIENT against the compositor that already exists, instead
  # of through Xwayland. This is the ONLY configuration in which Chromium reaches the GPU here --
  # the A/B on 2026-09-13 measured 0 render-node fds and 3 GPU-process crashes under Xwayland
  # against 9 fds and 0 crashes native. DISPLAY is deliberately NOT passed: with both set,
  # ozone's auto-detection is not something to leave to chance.
  # The old warning here said a Wayland client is INVISIBLE on the stream, because it is a sway
  # surface rather than part of the Xwayland root window Sunshine captured. That was true of the
  # X11 build and is now WRONG: there is no Xwayland and no X server at all, capture is
  # zwlr_screencopy against the compositor's own output, and input arrives through /dev/uinput
  # rather than XTest. A Wayland client is the ONLY kind there is here, and it is fully visible
  # to both Sunshine and wayvnc. This is no longer a measurement-only mode.
  # DISPVAR and OZONE were resolved in section 3b, before the self-test, so both launches
  # use exactly the same display environment.
  echo "   display env: \$DISPVAR \$OZONE"
  sudo -u "\$USER_NAME" setsid env \
    "\$DISPVAR" \
    XDG_RUNTIME_DIR="/run/user/\$(id -u "\$USER_NAME")" \
    DBUS_SESSION_BUS_ADDRESS="\$DBUS_ADDR" \
    "\$BROWSER" \$OZONE --no-first-run --no-default-browser-check \
      --password-store=basic \
      --trace-config-file="\$TRACECFG" \
      --enable-tracing="\$CATEGORIES" --enable-tracing-format=json \
      --enable-tracing-output="\$OUT" --trace-startup-duration="\$DURATION" \
      "\$URL" >"\$LOG" 2>&1 </dev/null &
fi

sleep 12

# --- 7. fail fast if the launch was rejected -----------------------------------------
# Firefox prints its profiler help and records NOTHING when an option is bad, but keeps
# running. Attempt one sat in exactly that state for minutes.
if grep -qiE 'unrecognized|invalid' "\$LOG" 2>/dev/null; then
  echo
  grep -iE 'unrecognized|invalid' "\$LOG" | head -5
  fail "\$ENGINE rejected an option (above). It is NOT recording. Nothing was captured."
fi

PIDS=\$(browser_pids | wc -l)
[ "\${PIDS:-0}" -gt 0 ] || fail "\$ENGINE did not stay running -- see \$LOG on the host"

echo "  ok  no rejected options"
echo "  ok  \$PIDS \$ENGINE process(es) running"
echo
echo "RECORDING. Load the game and play it."
if [ "\$ENGINE" = firefox ]; then
  echo "  firefox: --finish sends SIGUSR2, which dumps the profile and STOPS profiling."
  echo "  It does NOT close Firefox. Your session, tabs and game keep running."
  echo "  The buffer keeps only the most recent samples, so run --finish while the game"
  echo "  is IN THE SLOW PART."
else
  echo "  chromium: the window CLOSES AT \$(date -d @\$(cat \$DEADLINE) '+%H:%M:%S') (\$DURATION s) and"
  echo "  CANNOT be ended early -- closing the browser finalises nothing on this build. Be in"
  echo "  the state you want captured at that moment; only the last \${BUFKB}KB survive."
  echo "  --finish waits for it and then collects. Nothing is killed."
fi
REMOTE
  exit 0
fi

# ---------------------------------------------------------------------------- finish

if [ "$MODE" = finish ]; then
  remote <<REMOTE
set -euo pipefail

USER_NAME="$DESKTOP_USER"
DISPLAY_NUM="$DISPLAY_NUM"
DUMPDIR="$DUMPDIR"
OUT="$OUT"
LOG="$LOG"
DEADLINE="$DEADLINE"
BROWSER="$BROWSER"
ENGINE="$ENGINE"

$(prelude)

if [ "\$ENGINE" = firefox ]; then
  RUNNING=\$(browser_pids)
  [ -n "\$RUNNING" ] || fail "no \$ENGINE running as \$USER_NAME -- nothing to finish."
  PARENTS=\$(browser_parents)
  [ -n "\$PARENTS" ] || fail "found \$ENGINE processes but no parent among them -- refusing to
       signal a tree I cannot identify. Check 'ps -ef | grep \$ENGINE' on the host."

  # The crash helper matches the engine name but is not the browser; never signal it.
  MAIN=""
  for p in \$PARENTS; do
    c=\$(tr '\\0' ' ' < "/proc/\$p/cmdline" 2>/dev/null || true)
    case "\$c" in *crashhelper*) ;; *) MAIN="\$MAIN \$p" ;; esac
  done
  [ -n "\$MAIN" ] || fail "only a crash helper matched -- no browser parent to signal."

  # HOW THIS WORKS, and why it is not a kill. Read out of gecko tools/profiler/core/platform.cpp
  # and verified against the INSTALLED libxul (AsyncSignalControlThread and
  # profiler_dump_and_stop are both present in Firefox 155.0.1 on this host):
  #
  #   SIGUSR1 -> profiler_start_from_signal()  : start profiling, default presets
  #   SIGUSR2 -> profiler_dump_and_stop()      : WRITE THE PROFILE TO DISK, then stop
  #
  # profiler_dump_and_stop pauses, saves, and stops. It does NOT exit the browser. Firefox,
  # the tabs and anything running in them survive, which is the entire point: the previous two
  # implementations here ended the browser (SIGTERM, then window-close) and between them cost a
  # live game session and its save file. A profiler must never be able to do that.
  #
  # The output path is chosen by Gecko and cannot be overridden -- platform.cpp
  # profiler_find_dump_path(): <download dir>/profile_<processtype>_<pid>.json, and the parent
  # process type is 0. MOZ_PROFILER_SHUTDOWN is NOT used by this path.
  echo "== SIGUSR2: dump the profile and stop profiling =="
  echo "   Firefox is NOT closed. Your session and the game keep running."
  EXPECT=""
  for p in \$MAIN; do
    echo "   SIGUSR2 -> pid \$p"
    sudo kill -s USR2 "\$p" 2>/dev/null || true
    EXPECT="\$EXPECT \$DUMPDIR/profile_0_\$p.json"
  done

  # Symbolication happens at dump time and is slow on a loaded host, so wait for the file to
  # stop growing rather than for a fixed time.
  prev=-1
  for i in \$(seq 1 60); do
    sleep 5
    sz=0
    for f in \$EXPECT; do
      s2=\$(sudo stat -c %s "\$f" 2>/dev/null || echo 0)
      sz=\$((sz + s2))
    done
    live=\$(browser_pids | wc -l)
    echo "   t=\$((i*5))s \$ENGINE=\$live (still running, as intended) dump=\$sz bytes"
    if [ "\$sz" != "0" ] && [ "\$sz" = "\$prev" ]; then break; fi
    prev=\$sz
  done

  FOUND=""
  for f in \$EXPECT; do
    sudo test -s "\$f" && FOUND="\$FOUND \$f"
  done
  [ -n "\$FOUND" ] || fail "SIGUSR2 produced no dump under \$DUMPDIR.
       Expected one of:\$EXPECT
       Firefox is still running -- nothing was lost, and you can retry.
       If \$DUMPDIR does not exist, Gecko logs \"Failed to find a valid dump path\" and writes
       nothing; create it and re-run --finish."
  # Deliberately no awk-first-field idiom here. Inside this heredoc an unescaped positional
  # parameter is expanded by the LOCAL shell, which under set -u aborts before anything is
  # sent -- and the error is reported at the heredoc's opening line, not the offending one.
  # This comment does not spell the idiom out, because the first version of this very comment
  # CONTAINED it and tripped the bug it was describing. Same family as the backticks-in-a-
  # heredoc trap in the header: a comment is not inert in an unquoted heredoc.
  for f in \$FOUND; do OUT="\$f"; break; done
  echo "   dump: \$OUT"
else
  # Chromium is NEVER signalled here, and that is a MEASURED constraint rather than caution.
  #
  # 2026-09-13 00:00: a --finish that SIGTERMed the parent of a Chromium with 600s of window
  # left produced NO FILE AT ALL -- not an empty one, none. Startup tracing writes its output
  # when tracing STOPS, and on this build only the duration expiring stops it. The self-test
  # proves the expiry path and ONLY the expiry path; it never exercised shutdown, and I
  # generalised from it anyway. It also contradicted a finding already recorded the evening
  # before -- "the flags are accepted but SIGTERM does not flush them".
  #
  # Closing the window through the UI is a DIFFERENT code path and may well work, but neither
  # xdotool nor wmctrl is installed on this host, so it cannot be driven from here. Do not
  # reintroduce a signal on this path without a control that tests shutdown specifically.
  #
  # The consequence is real and belongs in the open: the recording window is fixed at launch,
  # so the workload has to be in the interesting state when it closes. Keep --duration SHORT
  # and start it when the session is ready, rather than waiting out a long one.
  [ -r "\$DEADLINE" ] || fail "no \$DEADLINE on this host -- --start was never run for chromium."
  END=\$(cat "\$DEADLINE")
  NOW=\$(date +%s)
  if [ "\$NOW" -lt "\$END" ]; then
    echo "== the recording window is still open: \$((END - NOW))s remain =="
    echo "   It cannot be ended early -- see the note above. Keep the workload in the state you"
    echo "   want captured until it closes. Waiting."
  fi
  # Bound the wait on the deadline itself, not on a fixed count: a long --duration used to time
  # out here and then report "the window closed but the file is empty", which was a lie.
  TICKS=\$(( (END - NOW) / 5 + 60 ))
  prev=-1
  for i in \$(seq 1 \$TICKS); do
    NOW=\$(date +%s)
    sz=\$(stat -c %s "\$OUT" 2>/dev/null || echo 0)
    echo "   t=\$(date '+%H:%M:%S') remaining=\$(( END - NOW < 0 ? 0 : END - NOW ))s trace=\$sz bytes"
    if [ "\$NOW" -ge "\$END" ] && [ "\$sz" != "0" ] && [ "\$sz" = "\$prev" ]; then break; fi
    prev=\$sz
    sleep 5
  done

  [ -s "\$OUT" ] || fail "the window closed but \$OUT is empty or missing.
       Either the browser was closed before the window expired -- which finalises NOTHING on
       this build -- or the trace flags did not record. Run --selftest to tell the two apart;
       it takes 10 seconds and costs no session."

  # Did tracing run the whole window, or did the buffer fill and stop early? A ring buffer that
  # dropped the OLDEST events is the intended behaviour and finalises at the deadline. A buffer
  # that filled and stopped finalises long before it, and the trace then covers loading and
  # signing in rather than the interesting part -- a wrong answer that looks like a right one.
  MTIME=\$(stat -c %Y "\$OUT")
  if [ "\$MTIME" -lt "\$((END - 30))" ]; then
    fail "tracing stopped \$((END - MTIME))s BEFORE the window closed, so \$OUT covers the START
       of the session and not the end. --trace-config-file was ignored and the buffer filled
       under the default record-until-full mode. Lower BUFKB or shorten --duration."
  fi
  echo "  ok  tracing ran to the end of the window (trace finalised at the deadline)"
fi

# sudo: the ssh account is not the desktop user and /home/<desktop user> is 0700, so a bare
# stat here reports "Permission denied" on a file that exists and is perfectly readable by
# root. The head/tail/cat checks below already use sudo; this one was missed.
SIZE=\$(sudo stat -c %s "\$OUT")
# NEVER json.load this file. On 2026-09-13 a 120s capture came out at 667 MB and json.load of
# it took CT 120 to its 4 GB limit with swap full, 18467 cgroup limit hits, oom_kill 0 -- so
# the kernel never reaped it, sshd could not complete a handshake, and the hypervisor's load
# went to 99. The parse had to be killed by PID from vm-host-01. Validation here is therefore
# STRICTLY BOUNDED: first byte, last byte, line count. Content analysis is a separate,
# streaming tool -- scripts/vdesktop-01/trace-summarize.py -- which never holds more than one event.
FIRST=\$(sudo head -c 1 "\$OUT") \
  || fail "could not read \$OUT (\$SIZE bytes) -- a harness permission problem, not a verdict
       on the capture. The file is there."
case "\$FIRST" in
  '['|'{') ;;
  *) fail "\$OUT is \$SIZE bytes but starts with '\$FIRST', not { or [.
       For chromium this means the build ignored --enable-tracing-format=json and wrote proto:
       open it in Perfetto UI instead of parsing it as JSON." ;;
esac
LAST=\$(sudo tail -c 200 "\$OUT" | tr -d '[:space:]' | tail -c 1)
case "\$LAST" in
  ']'|'}') echo "  ok  file is closed (ends with '\$LAST'), so the write completed" ;;
  *) fail "\$OUT is \$SIZE bytes but ends with '\$LAST' -- the write was truncated." ;;
esac
LINES=\$(sudo cat "\$OUT" | wc -l)
echo "  ok  \$LINES lines (one trace event per line)"
if [ "\$SIZE" -gt 209715200 ]; then
  echo
  echo "  NOTE: \$((SIZE / 1048576)) MB. Do not open this with anything that reads it whole."
  echo "  Use: scripts/vdesktop-01/trace-summarize.sh \$(hostname) \$OUT"
fi
echo
echo "OK: \$OUT  (\$SIZE bytes, well-formed)"
echo "Fetch it with:  scp \$(hostname):\$OUT ."
REMOTE
  exit 0
fi
