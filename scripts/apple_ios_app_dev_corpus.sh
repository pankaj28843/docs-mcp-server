#!/usr/bin/env bash
# Build a divided iOS app-development documentation corpus.
#
# This intentionally keeps Apple DocC (/documentation/) as the generated
# filesystem tenant and adds separate online tenants for the rich non-DocC Apple
# surfaces: HIG, design resources/tools, App Store/App Store Connect, account
# signing/provisioning help, Swift language docs, Objective-C archive docs,
# tutorials, and WWDC sessions.

set -Eeuo pipefail

ROOT="${ROOT:-tmp/apple-ios-app-dev-corpus}"
RESEARCH_ROOT="${RESEARCH_ROOT:-tmp/research-web-critical/apple-ios-app-dev-docs}"
CONFIG="${CONFIG:-deployment.json}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-42042}"
REFRESH_MAX_AGE_HOURS="${REFRESH_MAX_AGE_HOURS:-72}"
DOCC_RESET="${DOCC_RESET:-0}"
DOCC_REFRESH_URLS="${DOCC_REFRESH_URLS:-0}"
INCLUDE_WWDC="${INCLUDE_WWDC:-0}"

CORE_ONLINE_TENANTS=(
  apple-hig
  apple-design-resources
  apple-app-store
  apple-app-store-connect
  apple-developer-account
  swift-language
  apple-objc-archive
  apple-tutorials-ios
)
OPTIONAL_ONLINE_TENANTS=(apple-wwdc-ios)
ONLINE_TENANTS=("${CORE_ONLINE_TENANTS[@]}")
if [[ "$INCLUDE_WWDC" == "1" || "$INCLUDE_WWDC" == "true" ]]; then
  ONLINE_TENANTS+=("${OPTIONAL_ONLINE_TENANTS[@]}")
fi

ALL_INDEX_TENANTS=(apple-developer "${ONLINE_TENANTS[@]}")

APPLE_DOCC_SCOPE=(
  --scope-term swift
  --scope-term swiftui
  --scope-term uikit
  --scope-term objective-c
  --scope-term objectivec
  --scope-term objc
  --scope-term ios
  --scope-term ipados
  --scope-term xcode
  --scope-term foundation
  --scope-term accessibility
  --scope-term design
  --scope-term interface
  --scope-term layout
  --scope-term navigation
  --scope-term animation
  --scope-term gesture
  --scope-term controls
  --scope-term settings
  --scope-term file
  --scope-term app
  --scope-term storekit
  --scope-term testflight
  --include-url-regex '/documentation/(swift|swiftui|uikit|foundation|xcode|objective[-_]?c|objectivec|accessibility|storekit|coredata|cloudkit|security|usernotifications|avfoundation|photosui|photokit|mapkit|widgetkit|appintents|localauthentication|network|urlsession|combine|observation|testing|samplecode|technologyoverviews)(/|$|-|_)'
  --include-url-regex '/documentation/.*/(ios|ipad|swift|uikit|swiftui|objective[-_]?c|objc|design|interface|accessibility|layout|navigation|animation|gesture|control|settings|file|document|view|controller|scene|lifecycle|app-store|testflight)'
)

usage() {
  cat <<'EOF'
Usage: scripts/apple_ios_app_dev_corpus.sh <command>

Commands:
  preflight          Check local tools and safe cdp daemon health.
  research-serp      Run browser-grounded Google SERP discovery into tmp/.
  add-tenants        Backup deployment.json, add/update divided online tenants, validate config.
  docc               Crawl/render scoped Apple DocC /documentation/ corpus; resumes by default.
  docc-bfs           Resume only the scoped DocC rendered-link BFS.
  docc-render        Render snapshot from DocC JSON plus the latest BFS URL file.
  docc-reset         Fresh scoped DocC crawl, then render snapshot.
  sync-online        Trigger online sync for divided core tenants; requires server already running.
  index              Rebuild indexes for apple-developer and divided core tenants.
  export-data        Export apple-developer and divided core tenant data.
  verify             Run docsearch smoke queries.
  app-examples       Extract the App Store app examples from this brief into tmp/ only.
  all-local          preflight + research-serp + add-tenants + docc + index. Does not start server.

Environment overrides:
  ROOT=tmp/apple-ios-app-dev-corpus
  RESEARCH_ROOT=tmp/research-web-critical/apple-ios-app-dev-docs
  CONFIG=deployment.json
  HOST=127.0.0.1 PORT=42042
  REFRESH_MAX_AGE_HOURS=72
  DOCC_RESET=0       # set to 1 to discard the DocC BFS checkpoint
  DOCC_REFRESH_URLS=0 # set to 1 to rediscover DocC JSON URLs even if the URL file exists
  INCLUDE_WWDC=0     # set to 1 to include the high-noise optional WWDC tenant in sync/index/verify

Notes:
  - Do not use --clean for scoped DocC refreshes; this script intentionally omits it.
  - WWDC is added as a separate optional tenant; set INCLUDE_WWDC=1 to sync/index it.
  - sync-online expects the MCP server to be running with the updated deployment.json.
EOF
}

require_cmd() {
  command -v "$1" >/dev/null || { echo "missing required command: $1" >&2; exit 1; }
}

preflight() {
  require_cmd uv
  require_cmd cdp
  require_cmd jq
  require_cmd curl
  cdp --help >/dev/null
  cdp workflow web-research serp --help >/dev/null
  cdp workflow web-research extract --help >/dev/null
  uv run python scripts/apple_rendered_link_bfs.py --help >/dev/null
  uv run python scripts/apple_docc_snapshot.py --help >/dev/null

  local health state
  health="$(cdp daemon health --json)"
  state="$(printf '%s' "$health" | jq -r '.health.state // .daemon.health.state // empty')"
  if [[ "$state" != "healthy" ]]; then
    printf '%s\n' "$health" \
      | jq '{ok, human_required, agent_should_stop, human_action, safe_diagnostics, health: (.health // .daemon.health)}'
    echo "cdp daemon is not healthy; ask the human to repair/approve cdp before crawling." >&2
    exit 1
  fi
  echo "preflight OK"
}

write_research_inputs() {
  mkdir -p "$RESEARCH_ROOT"
  cat > "$RESEARCH_ROOT/queries.txt" <<'EOF'
site:developer.apple.com/design/human-interface-guidelines iOS app design navigation controls dark mode settings file management
site:developer.apple.com/documentation iOS app development Swift SwiftUI UIKit Objective-C Xcode
site:developer.apple.com/tutorials iOS app development SwiftUI UIKit Xcode
site:developer.apple.com/help/app-store-connect iOS app TestFlight app privacy app review in-app purchases subscriptions
site:developer.apple.com/help/account certificates identifiers provisioning profiles entitlements iOS app
site:developer.apple.com/app-store app review guidelines app privacy iOS apps
site:developer.apple.com/design/resources iOS app design resources Figma Sketch SF Symbols
site:developer.apple.com/videos/play/wwdc iOS app design SwiftUI UIKit Xcode accessibility
site:docs.swift.org Swift language guide standard library
site:developer.apple.com/library/archive Objective-C programming guide UIKit iOS
EOF
}

research_serp() {
  preflight
  write_research_inputs
  cdp workflow web-research serp \
    --query-file "$RESEARCH_ROOT/queries.txt" \
    --result-pages 2 \
    --serp google \
    --max-candidates 250 \
    --candidate-out "$RESEARCH_ROOT/candidates.json" \
    --out-dir "$RESEARCH_ROOT" \
    --parallel 1 \
    --min-visible-words 50 \
    --min-html-chars 1000 \
    --min-markdown-words 50 \
    --json > "$RESEARCH_ROOT/serp-summary.json"

  jq '{ok, workflow, queries, failures, artifacts}' "$RESEARCH_ROOT/serp-summary.json"
  sed -n '1,120p' "$RESEARCH_ROOT/candidates.tsv"
}

add_tenants() {
  mkdir -p tmp/backups
  cp "$CONFIG" "tmp/backups/$(basename "$CONFIG").$(date +%Y%m%d-%H%M%S)"
  uv run python - <<'PY'
from __future__ import annotations

import json
import os
from pathlib import Path

from docs_mcp_server.deployment_config import DeploymentConfig

config_path = Path(os.environ.get("CONFIG", "deployment.json"))
config = json.loads(config_path.read_text(encoding="utf-8"))

HIG_ENTRY_URLS = """
https://developer.apple.com/design/human-interface-guidelines
https://developer.apple.com/design/human-interface-guidelines/accessibility
https://developer.apple.com/design/human-interface-guidelines/activity-rings
https://developer.apple.com/design/human-interface-guidelines/activity-views
https://developer.apple.com/design/human-interface-guidelines/airplay
https://developer.apple.com/design/human-interface-guidelines/alerts
https://developer.apple.com/design/human-interface-guidelines/app-icons
https://developer.apple.com/design/human-interface-guidelines/augmented-reality
https://developer.apple.com/design/human-interface-guidelines/branding
https://developer.apple.com/design/human-interface-guidelines/buttons
https://developer.apple.com/design/human-interface-guidelines/charting-data
https://developer.apple.com/design/human-interface-guidelines/collaboration-and-sharing
https://developer.apple.com/design/human-interface-guidelines/color
https://developer.apple.com/design/human-interface-guidelines/components
https://developer.apple.com/design/human-interface-guidelines/content
https://developer.apple.com/design/human-interface-guidelines/context-menus
https://developer.apple.com/design/human-interface-guidelines/dark-mode
https://developer.apple.com/design/human-interface-guidelines/disclosure-controls
https://developer.apple.com/design/human-interface-guidelines/dock-menus
https://developer.apple.com/design/human-interface-guidelines/drag-and-drop
https://developer.apple.com/design/human-interface-guidelines/edit-menus
https://developer.apple.com/design/human-interface-guidelines/entering-data
https://developer.apple.com/design/human-interface-guidelines/feedback
https://developer.apple.com/design/human-interface-guidelines/file-management
https://developer.apple.com/design/human-interface-guidelines/foundations
https://developer.apple.com/design/human-interface-guidelines/gauges
https://developer.apple.com/design/human-interface-guidelines/getting-started
https://developer.apple.com/design/human-interface-guidelines/going-full-screen
https://developer.apple.com/design/human-interface-guidelines/healthkit
https://developer.apple.com/design/human-interface-guidelines/home-screen-quick-actions
https://developer.apple.com/design/human-interface-guidelines/homekit
https://developer.apple.com/design/human-interface-guidelines/icons
https://developer.apple.com/design/human-interface-guidelines/images
https://developer.apple.com/design/human-interface-guidelines/immersive-experiences
https://developer.apple.com/design/human-interface-guidelines/inclusion
https://developer.apple.com/design/human-interface-guidelines/inputs
https://developer.apple.com/design/human-interface-guidelines/launching
https://developer.apple.com/design/human-interface-guidelines/layout
https://developer.apple.com/design/human-interface-guidelines/layout-and-organization
https://developer.apple.com/design/human-interface-guidelines/lists-and-tables
https://developer.apple.com/design/human-interface-guidelines/live-viewing-apps
https://developer.apple.com/design/human-interface-guidelines/loading
https://developer.apple.com/design/human-interface-guidelines/managing-accounts
https://developer.apple.com/design/human-interface-guidelines/managing-notifications
https://developer.apple.com/design/human-interface-guidelines/materials
https://developer.apple.com/design/human-interface-guidelines/menus
https://developer.apple.com/design/human-interface-guidelines/menus-and-actions
https://developer.apple.com/design/human-interface-guidelines/modality
https://developer.apple.com/design/human-interface-guidelines/motion
https://developer.apple.com/design/human-interface-guidelines/multitasking
https://developer.apple.com/design/human-interface-guidelines/navigation-and-search
https://developer.apple.com/design/human-interface-guidelines/navigation-bars
https://developer.apple.com/design/human-interface-guidelines/offering-help
https://developer.apple.com/design/human-interface-guidelines/onboarding
https://developer.apple.com/design/human-interface-guidelines/ornaments
https://developer.apple.com/design/human-interface-guidelines/patterns
https://developer.apple.com/design/human-interface-guidelines/patterns/accessing-private-data
https://developer.apple.com/design/human-interface-guidelines/patterns/workouts
https://developer.apple.com/design/human-interface-guidelines/playing-audio
https://developer.apple.com/design/human-interface-guidelines/playing-haptics
https://developer.apple.com/design/human-interface-guidelines/playing-video
https://developer.apple.com/design/human-interface-guidelines/pop-up-buttons
https://developer.apple.com/design/human-interface-guidelines/presentation
https://developer.apple.com/design/human-interface-guidelines/printing
https://developer.apple.com/design/human-interface-guidelines/privacy
https://developer.apple.com/design/human-interface-guidelines/progress-indicators
https://developer.apple.com/design/human-interface-guidelines/pull-down-buttons
https://developer.apple.com/design/human-interface-guidelines/rating-indicators
https://developer.apple.com/design/human-interface-guidelines/ratings-and-reviews
https://developer.apple.com/design/human-interface-guidelines/right-to-left
https://developer.apple.com/design/human-interface-guidelines/search-fields
https://developer.apple.com/design/human-interface-guidelines/searching
https://developer.apple.com/design/human-interface-guidelines/selection-and-input
https://developer.apple.com/design/human-interface-guidelines/settings
https://developer.apple.com/design/human-interface-guidelines/sf-symbols
https://developer.apple.com/design/human-interface-guidelines/sidebars
https://developer.apple.com/design/human-interface-guidelines/sign-in-with-apple
https://developer.apple.com/design/human-interface-guidelines/spatial-layout
https://developer.apple.com/design/human-interface-guidelines/status
https://developer.apple.com/design/human-interface-guidelines/system-experiences
https://developer.apple.com/design/human-interface-guidelines/tab-bars
https://developer.apple.com/design/human-interface-guidelines/technologies
https://developer.apple.com/design/human-interface-guidelines/the-menu-bar
https://developer.apple.com/design/human-interface-guidelines/toolbars
https://developer.apple.com/design/human-interface-guidelines/typography
https://developer.apple.com/design/human-interface-guidelines/undo-and-redo
https://developer.apple.com/design/human-interface-guidelines/windows
https://developer.apple.com/design/human-interface-guidelines/workouts
https://developer.apple.com/design/human-interface-guidelines/writing
""".strip().splitlines()

SWIFT_ENTRY_URLS = """
https://docs.swift.org/swift-book/documentation/the-swift-programming-language
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/aboutswift
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/aboutthelanguagereference
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/accesscontrol
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/advancedoperators
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/attributes
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/automaticreferencecounting
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/basicoperators
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/classesandstructures
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/closures
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/collectiontypes
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/compatibility
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/concurrency
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/controlflow
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/declarations
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/deinitialization
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/enumerations
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/errorhandling
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/expressions
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/extensions
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/functions
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/genericparametersandarguments
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/generics
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/guidedtour
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/inheritance
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/initialization
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/lexicalstructure
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/macros
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/memorysafety
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/methods
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/nestedtypes
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/opaquetypes
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/optionalchaining
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/patterns
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/properties
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/protocols
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/revisionhistory
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/statements
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/stringsandcharacters
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/subscripts
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/summaryofthegrammar
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/thebasics
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/typecasting
https://docs.swift.org/swift-book/documentation/the-swift-programming-language/types
""".strip().splitlines()

OBJC_ENTRY_URLS = """
https://developer.apple.com/library/archive/documentation/Cocoa/Conceptual/ProgrammingWithObjectiveC/index.html
https://developer.apple.com/library/archive/documentation/Cocoa/Conceptual/ProgrammingWithObjectiveC/Introduction/Introduction.html
https://developer.apple.com/library/archive/documentation/Cocoa/Conceptual/ProgrammingWithObjectiveC/DefiningClasses/DefiningClasses.html
https://developer.apple.com/library/archive/documentation/Cocoa/Conceptual/ProgrammingWithObjectiveC/EncapsulatingData/EncapsulatingData.html
https://developer.apple.com/library/archive/documentation/Cocoa/Conceptual/ProgrammingWithObjectiveC/WorkingwithObjects/WorkingwithObjects.html
https://developer.apple.com/library/archive/documentation/Cocoa/Conceptual/ProgrammingWithObjectiveC/CustomizingExistingClasses/CustomizingExistingClasses.html
https://developer.apple.com/library/archive/documentation/Cocoa/Conceptual/ProgrammingWithObjectiveC/WorkingwithProtocols/WorkingwithProtocols.html
https://developer.apple.com/library/archive/documentation/Cocoa/Conceptual/ProgrammingWithObjectiveC/WorkingwithBlocks/WorkingwithBlocks.html
https://developer.apple.com/library/archive/documentation/Cocoa/Conceptual/ProgrammingWithObjectiveC/FoundationTypesandCollections/FoundationTypesandCollections.html
https://developer.apple.com/library/archive/documentation/Cocoa/Conceptual/ProgrammingWithObjectiveC/ErrorHandling/ErrorHandling.html
https://developer.apple.com/library/archive/documentation/Cocoa/Conceptual/ProgrammingWithObjectiveC/Conventions/Conventions.html
https://developer.apple.com/library/archive/documentation/Cocoa/Conceptual/ProgrammingWithObjectiveC/RevisionHistory.html
https://developer.apple.com/library/archive/documentation/Cocoa/Conceptual/ObjCRuntimeGuide/Introduction/Introduction.html
https://developer.apple.com/library/archive/documentation/Cocoa/Conceptual/MemoryMgmt/Articles/MemoryMgmt.html
https://developer.apple.com/library/archive/documentation/General/Conceptual/CocoaEncyclopedia/Introduction/Introduction.html
https://developer.apple.com/library/archive/documentation/General/Conceptual/DevPedia-CocoaCore/ObjectiveC.html
https://developer.apple.com/library/archive/releasenotes/ObjectiveC/ObjCAvailabilityIndex/index.html
""".strip().splitlines()

TUTORIAL_ENTRY_URLS = """
https://developer.apple.com/tutorials/swiftui
https://developer.apple.com/tutorials/swiftui/creating-and-combining-views
https://developer.apple.com/tutorials/swiftui/building-lists-and-navigation
https://developer.apple.com/tutorials/swiftui/handling-user-input
https://developer.apple.com/tutorials/swiftui/drawing-paths-and-shapes
https://developer.apple.com/tutorials/swiftui/animating-views-and-transitions
https://developer.apple.com/tutorials/swiftui/composing-complex-interfaces
https://developer.apple.com/tutorials/swiftui/working-with-ui-controls
https://developer.apple.com/tutorials/swiftui/interfacing-with-uikit
https://developer.apple.com/tutorials/develop-in-swift
https://developer.apple.com/tutorials/app-dev-training
""".strip().splitlines()

new_tenants = [
    {
        "source_type": "online",
        "codename": "apple-hig",
        "docs_name": "Apple Human Interface Guidelines",
        "docs_entry_url": HIG_ENTRY_URLS,
        "url_whitelist_prefixes": "https://developer.apple.com/design/human-interface-guidelines/",
        "enable_crawler": True,
        "max_crawl_pages": 1500,
        "docs_root_dir": "./mcp-data/apple-hig",
        "refresh_schedule": "17 3 * * 0",
        "test_queries": {
            "natural": [
                "how should progress indicators work in an iOS app",
                "how should iOS apps handle file management and settings",
            ],
            "phrases": ["Designing for iOS", "Dark Mode", "Navigation bars"],
            "words": ["accessibility", "navigation", "layout"],
        },
    },
    {
        "source_type": "online",
        "codename": "apple-design-resources",
        "docs_name": "Apple Design Resources and Tools",
        "docs_entry_url": "https://developer.apple.com/design/resources/,https://developer.apple.com/sf-symbols/,https://developer.apple.com/fonts/,https://developer.apple.com/xcode/resources/",
        "url_whitelist_prefixes": "https://developer.apple.com/design/resources/,https://developer.apple.com/sf-symbols/,https://developer.apple.com/fonts/,https://developer.apple.com/xcode/resources/",
        "enable_crawler": True,
        "max_crawl_pages": 500,
        "docs_root_dir": "./mcp-data/apple-design-resources",
        "refresh_schedule": "29 3 * * 0",
        "test_queries": {
            "natural": ["where are Apple design templates for iOS apps", "how do I use SF Symbols in app design"],
            "phrases": ["Apple Design Resources", "SF Symbols", "Fonts"],
            "words": ["Figma", "Sketch", "symbols"],
        },
    },
    {
        "source_type": "online",
        "codename": "apple-app-store",
        "docs_name": "Apple App Store Guidelines and Distribution",
        "docs_entry_url": "https://developer.apple.com/app-store/,https://developer.apple.com/app-store/review/guidelines/,https://developer.apple.com/app-store/app-privacy-details/,https://developer.apple.com/app-store/submitting/",
        "url_whitelist_prefixes": "https://developer.apple.com/app-store/",
        "enable_crawler": True,
        "max_crawl_pages": 1200,
        "docs_root_dir": "./mcp-data/apple-app-store",
        "refresh_schedule": "41 3 * * 0",
        "test_queries": {
            "natural": ["what are App Store review guidelines for iOS apps", "how do app privacy details work"],
            "phrases": ["App Review Guidelines", "App Privacy Details", "Submitting"],
            "words": ["privacy", "review", "ratings"],
        },
    },
    {
        "source_type": "online",
        "codename": "apple-app-store-connect",
        "docs_name": "App Store Connect Help",
        "docs_entry_url": "https://developer.apple.com/help/app-store-connect/",
        "url_whitelist_prefixes": "https://developer.apple.com/help/app-store-connect/",
        "enable_crawler": True,
        "max_crawl_pages": 5000,
        "docs_root_dir": "./mcp-data/apple-app-store-connect",
        "refresh_schedule": "53 3 * * 0",
        "test_queries": {
            "natural": ["how do I submit an app for review", "how do I test subscriptions in TestFlight"],
            "phrases": ["TestFlight overview", "Overview of submitting for review", "App information"],
            "words": ["TestFlight", "subscriptions", "sandbox"],
        },
    },
    {
        "source_type": "online",
        "codename": "apple-developer-account",
        "docs_name": "Apple Developer Account Help",
        "docs_entry_url": "https://developer.apple.com/help/account/,https://developer.apple.com/support/certificates/,https://developer.apple.com/programs/",
        "url_whitelist_prefixes": "https://developer.apple.com/help/account/,https://developer.apple.com/support/certificates/,https://developer.apple.com/programs/",
        "enable_crawler": True,
        "max_crawl_pages": 1000,
        "docs_root_dir": "./mcp-data/apple-developer-account",
        "refresh_schedule": "7 4 * * 0",
        "test_queries": {
            "natural": ["how do provisioning profiles work", "how do I manage certificates and identifiers"],
            "phrases": ["Certificates", "Identifiers", "Provisioning profiles"],
            "words": ["entitlements", "profiles", "certificates"],
        },
    },
    {
        "source_type": "online",
        "codename": "swift-language",
        "docs_name": "Swift Language Documentation",
        "docs_entry_url": SWIFT_ENTRY_URLS,
        "url_whitelist_prefixes": "https://docs.swift.org/swift-book/",
        "enable_crawler": True,
        "max_crawl_pages": 3000,
        "docs_root_dir": "./mcp-data/swift-language",
        "refresh_schedule": "19 4 * * 0",
        "search": {"analyzer_profile": "code-friendly"},
        "test_queries": {
            "natural": ["how do Swift protocols and generics work", "how does Swift concurrency work"],
            "phrases": ["The Swift Programming Language", "Concurrency", "Generics"],
            "words": ["protocol", "actor", "optional"],
        },
    },
    {
        "source_type": "online",
        "codename": "apple-objc-archive",
        "docs_name": "Apple Objective-C and Cocoa Archive",
        "docs_entry_url": OBJC_ENTRY_URLS,
        "url_whitelist_prefixes": "https://developer.apple.com/library/archive/documentation/Cocoa/Conceptual/ProgrammingWithObjectiveC/,https://developer.apple.com/library/archive/documentation/General/Conceptual/DevPedia-CocoaCore/",
        "enable_crawler": True,
        "max_crawl_pages": 800,
        "docs_root_dir": "./mcp-data/apple-objc-archive",
        "refresh_schedule": "31 4 * * 0",
        "search": {"analyzer_profile": "code-friendly"},
        "test_queries": {
            "natural": ["how does Objective-C messaging work", "how do I expose Objective-C to Swift"],
            "phrases": ["Programming with Objective-C", "Objective-C Runtime", "Categories"],
            "words": ["NSObject", "selector", "protocol"],
        },
    },
    {
        "source_type": "online",
        "codename": "apple-tutorials-ios",
        "docs_name": "Apple iOS and SwiftUI Tutorials",
        "docs_entry_url": TUTORIAL_ENTRY_URLS,
        "url_whitelist_prefixes": "https://developer.apple.com/tutorials/swiftui,https://developer.apple.com/tutorials/app-dev-training,https://developer.apple.com/tutorials/develop-in-swift",
        "enable_crawler": True,
        "max_crawl_pages": 3000,
        "docs_root_dir": "./mcp-data/apple-tutorials-ios",
        "refresh_schedule": "43 4 * * 0",
        "search": {"analyzer_profile": "code-friendly"},
        "test_queries": {
            "natural": ["how do I build an iOS app with SwiftUI", "how do I use Xcode previews"],
            "phrases": ["SwiftUI Tutorials", "App Dev Training", "Develop in Swift"],
            "words": ["SwiftUI", "Xcode", "preview"],
        },
    },
    {
        "source_type": "online",
        "codename": "apple-wwdc-ios",
        "docs_name": "Apple WWDC iOS App Development Sessions",
        "docs_entry_url": "https://developer.apple.com/videos/",
        "url_whitelist_prefixes": "https://developer.apple.com/videos/play/wwdc",
        "enable_crawler": True,
        "max_crawl_pages": 3000,
        "docs_root_dir": "./mcp-data/apple-wwdc-ios",
        "refresh_schedule": "55 4 * * 0",
        "search": {"analyzer_profile": "code-friendly"},
        "test_queries": {
            "natural": ["WWDC SwiftUI UIKit iOS design session", "WWDC app accessibility session"],
            "phrases": ["WWDC", "SwiftUI", "Design"],
            "words": ["UIKit", "accessibility", "Xcode"],
        },
    },
]

existing = {tenant["codename"]: tenant for tenant in config["tenants"]}
for tenant in new_tenants:
    codename = tenant["codename"]
    if codename in existing:
        existing[codename].clear()
        existing[codename].update(tenant)
        print(f"Updated: {codename}")
    else:
        config["tenants"].append(tenant)
        print(f"Added: {codename}")

config["tenants"].sort(key=lambda tenant: tenant["codename"])
DeploymentConfig(**config)
config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
print(f"Validation passed ({len(config['tenants'])} total tenants)")
PY
}

docc_bfs() {
  preflight
  mkdir -p "$ROOT"
  local reset_args=()
  if [[ "$DOCC_RESET" == "1" || "$DOCC_RESET" == "true" ]]; then
    reset_args=(--reset)
  fi
  uv run python scripts/apple_rendered_link_bfs.py \
    "${reset_args[@]}" \
    --seed-docc-root-groups \
    "${APPLE_DOCC_SCOPE[@]}" \
    --urls-file "$ROOT/apple-docc-ios-app-dev-rendered-bfs-urls.json" \
    --state-file "$ROOT/apple-docc-ios-app-dev-rendered-bfs-state.json" \
    --checkpoint-every 25 \
    --retries 3 \
    --wait-timeout 20s \
    --settle-seconds 2 \
    --poll-seconds 1 \
    2>&1 | tee -a "$ROOT/apple-docc-ios-app-dev-rendered-bfs.log"
}

docc_render() {
  mkdir -p "$ROOT"
  local urls_file="$ROOT/apple-docc-ios-app-dev-urls.json"
  local snapshot_args=()
  if [[ -f "$urls_file" && "$DOCC_REFRESH_URLS" != "1" && "$DOCC_REFRESH_URLS" != "true" ]]; then
    snapshot_args=(--build-only)
  else
    snapshot_args=(--extra-urls-file "$ROOT/apple-docc-ios-app-dev-rendered-bfs-urls.json")
  fi
  uv run python scripts/apple_docc_snapshot.py \
    --docs-root mcp-data/apple-developer \
    --urls-file "$urls_file" \
    "${snapshot_args[@]}" \
    "${APPLE_DOCC_SCOPE[@]}" \
    --refresh-max-age-hours "$REFRESH_MAX_AGE_HOURS" \
    --max-docs 0 \
    --discovery-limit 0 \
    2>&1 | tee "$ROOT/apple-docc-ios-app-dev-snapshot.log"
}

docc() {
  docc_bfs
  docc_render
}

sync_online() {
  if ! curl -sf "http://$HOST:$PORT/health" >/dev/null; then
    echo "MCP server is not reachable at http://$HOST:$PORT." >&2
    echo "Start it in another terminal: uv run python deploy_multi_tenant.py --mode online" >&2
    exit 1
  fi
  uv run python trigger_all_syncs.py --host "$HOST" --port "$PORT" --tenants "${ONLINE_TENANTS[@]}" --force
}

index_all() {
  uv run python trigger_all_indexing.py --tenants "${ALL_INDEX_TENANTS[@]}"
}

export_data() {
  uv run python sync_tenant_data.py export --tenants "${ALL_INDEX_TENANTS[@]}"
}

search_smoke() {
  local tenant="$1"
  local query="$2"
  local slug="$3"
  mkdir -p "$ROOT/verify"
  uv run docsearch search "$tenant" "$query" --json > "$ROOT/verify/$slug.json"
  head -80 "$ROOT/verify/$slug.json"
}

verify() {
  search_smoke apple-developer "SwiftUI UIKit Objective-C iOS app design accessibility" apple-developer
  search_smoke apple-hig "navigation bars dark mode file management progress indicators" apple-hig
  search_smoke swift-language "Swift concurrency protocols generics optional" swift-language
  search_smoke apple-app-store-connect "TestFlight subscriptions app review app privacy" apple-app-store-connect
  if [[ "$INCLUDE_WWDC" == "1" || "$INCLUDE_WWDC" == "true" ]]; then
    search_smoke apple-wwdc-ios "WWDC SwiftUI UIKit iOS design accessibility" apple-wwdc-ios
  fi
}

app_examples() {
  preflight
  mkdir -p "$ROOT/app-store-examples"
  cat > "$ROOT/app-store-examples/urls.txt" <<'EOF'
https://apps.apple.com/us/app/documents-file-manager-docs/id364901807
https://apps.apple.com/be/app/dlmanager-browse-download/id6755075565
https://apps.apple.com/us/app/dmanager-datamanager/id6478941471
https://apps.apple.com/ng/app/d-manager-idm/id1590633469
EOF
  cdp workflow web-research extract \
    --url-file "$ROOT/app-store-examples/urls.txt" \
    --max-pages 0 \
    --parallel 4 \
    --selector body \
    --out-dir "$ROOT/app-store-examples/pages" \
    --min-visible-words 50 \
    --min-html-chars 1000 \
    --min-markdown-words 50 \
    --json > "$ROOT/app-store-examples/extract-summary.json"
  jq '{ok, workflow, pages, warnings, failures, artifacts}' "$ROOT/app-store-examples/extract-summary.json"
}

case "${1:-}" in
  preflight) preflight ;;
  research-serp) research_serp ;;
  add-tenants) add_tenants ;;
  docc) docc ;;
  docc-bfs) docc_bfs ;;
  docc-render) docc_render ;;
  docc-reset) DOCC_RESET=1 docc ;;
  sync-online) sync_online ;;
  index) index_all ;;
  export-data) export_data ;;
  verify) verify ;;
  app-examples) app_examples ;;
  all-local)
    preflight
    research_serp
    add_tenants
    docc
    index_all
    ;;
  -h|--help|help|"") usage ;;
  *) echo "unknown command: $1" >&2; usage; exit 2 ;;
esac
