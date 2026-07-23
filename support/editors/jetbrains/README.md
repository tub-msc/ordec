<!-- SPDX-FileCopyrightText: 2026 ORDeC contributors -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# ORD plugin for JetBrains IDEs

An IntelliJ Platform plugin that parses ORD natively as a Python dialect,
extending the Python plugin's parser with the ORD constructs from
`ordec/ord/ord.lark` — the extension mechanism Cython support and the
SnakeCharm plugin use. Everything that is plain Python inherits the IDE's
Python intelligence, and `.ord` files get the ORDeC icon.

Requires an IDE with Python support — PyCharm, or IntelliJ IDEA with the
Python plugin — on platform 2024.2 or newer.

## Building

Requires only an installed JDK (17 or newer) to launch the committed Gradle
wrapper; the wrapper pins the Gradle version and auto-provisions the JDK
the IntelliJ Platform needs, so builds do not depend on locally installed
tool versions. The first build downloads the pinned Gradle distribution
(checksum-verified) and the IDE SDK.

    ./gradlew buildPlugin

The installable archive lands in `build/distributions/`. Install it via
`Settings > Plugins > (gear icon) > Install Plugin from Disk`.

`./gradlew runIde` starts a sandboxed IDE with the plugin for development.

## Status

Parsing is complete and oracle-tested. One known parsing edge remains: ORD
simple statements in the one-line suite of a plain Python compound
statement (``if x: net a``) are not recognized, since Python's own suite
parsing handles those bodies. Deeper IDE features are not implemented
yet: ORD constructs use generic PSI, so references on them do
not resolve (Ctrl+hover underlines without navigation), and there are no
ORD-specific annotators or completion. ORDeC-semantic features (analyzer
diagnostics, cross-view navigation) are planned through the ORD language
server, not this plugin.

The test suite mirrors `tests/test_editor_grammars.py`: every `.ord` file
in the repository must parse without PSI errors, plus synthetic positives
and soft-keyword negatives:

    ./gradlew test

Not yet built in CI and not yet published to the marketplace (the plugin id
is a placeholder).
