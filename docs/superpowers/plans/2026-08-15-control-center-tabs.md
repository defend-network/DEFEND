# Multi-Product Control Center Tabs Implementation Plan

**Goal:** Replace the long single-page Control Center presentation with Home plus dedicated product tabs.

**Architecture:** Keep ProductService lifecycle logic unchanged. ControlCenterUI owns presentation only: Home renders aggregate status/actions; each product tab renders ProductStatus.details, product actions, and that product's logs. DEFEND AI retains its identity-specific backend/Vast controls inside its own tab.

**Files:** defend_control/ui.py, tests/test_control_center_tabs.py

**Verification:** focused tab tests, control/product regression, manual visual launch.
