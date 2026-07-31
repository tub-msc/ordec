// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

package org.ordec.intellij;

import com.intellij.codeInsight.daemon.impl.HighlightInfo;
import com.intellij.lang.annotation.HighlightSeverity;
import com.intellij.psi.PsiElement;
import com.intellij.psi.PsiErrorElement;
import com.intellij.psi.PsiFile;
import com.intellij.psi.PsiRecursiveElementWalkingVisitor;
import com.intellij.psi.tree.IElementType;
import com.intellij.psi.tree.TokenSet;
import com.intellij.psi.util.PsiTreeUtil;
import com.intellij.testFramework.fixtures.BasePlatformTestCase;
import com.jetbrains.python.PythonDialectsTokenSetProvider;
import com.jetbrains.python.PythonLanguage;
import com.jetbrains.python.inspections.PyStatementEffectInspection;
import com.jetbrains.python.inspections.unresolvedReference.PyUnresolvedReferencesInspection;
import com.jetbrains.python.psi.PyAugAssignmentStatement;
import com.jetbrains.python.psi.PyExpression;
import com.jetbrains.python.psi.PyStatement;
import org.jetbrains.annotations.NotNull;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Collection;
import java.util.List;
import java.util.stream.Stream;

/**
 * The dialect's exit criterion, mirroring support/editors/tests/test_editor_grammars.py:
 * every .ord file in the repository must parse without PSI error elements.
 */
public class OrdDialectParsingTest extends BasePlatformTestCase {
    public void testRepositoryOrdFilesParse() throws IOException {
        Path repoRoot = findRepoRoot();
        List<Path> ordFiles = new ArrayList<>();
        for (String dir : new String[]{"ordec", "tests", "examples"}) {
            try (Stream<Path> walk = Files.walk(repoRoot.resolve(dir))) {
                walk.filter(p -> p.toString().endsWith(".ord")).sorted().forEach(ordFiles::add);
            }
        }
        assertFalse("no .ord files found under " + repoRoot, ordFiles.isEmpty());

        List<String> failures = new ArrayList<>();
        for (Path file : ordFiles) {
            PsiFile psi = myFixture.configureByText("case.ord", Files.readString(file));
            Collection<PsiErrorElement> errors =
                PsiTreeUtil.findChildrenOfType(psi, PsiErrorElement.class);
            if (!errors.isEmpty()) {
                PsiErrorElement first = errors.iterator().next();
                failures.add(repoRoot.relativize(file) + ": " + errors.size()
                    + " error(s), first at offset " + first.getTextOffset()
                    + ": " + first.getErrorDescription());
            }
        }
        System.out.println("ORD dialect: " + (ordFiles.size() - failures.size())
            + "/" + ordFiles.size() + " repository files parse cleanly");
        assertTrue("files with parse errors:\n" + String.join("\n", failures),
            failures.isEmpty());
    }

    /**
     * The synthetic positives from support/editors/tests/test_editor_grammars.py: kind and
     * target forms no repository .ord file exercises yet.
     */
    public void testAtomExprKindForms() {
        String[] statements = {
            "lib.Inv i0:\n            pass",
            "lib.Inv() i1:\n            pass",
            "rows[0] r0:\n            pass",
            "anonymous lib.Vdc(dc=1) v0:\n            pass",
            "lib.Inv i2, i3",
            "net vdd, ring.vx",
            "path ctr[0], ctr[1].sub",
            "path ctr[1:2]",
            "print foo:\n            pass",
        };
        for (String statement : statements) {
            String source = "cell C:\n    viewgen v -> Schematic:\n        " + statement + "\n";
            PsiFile psi = myFixture.configureByText("case.ord", source);
            Collection<PsiErrorElement> errors =
                PsiTreeUtil.findChildrenOfType(psi, PsiErrorElement.class);
            assertTrue("parse errors for: " + statement, errors.isEmpty());
        }
    }

    /**
     * ORD simple statements are legal in one-line suites, like expression
     * statements (suite in ord.lark).
     */
    public void testInlineSuites() {
        String[] statements = {
            "Nmos m1: ! .pos == (0, 0)",
            "Nmos m1: net a",
            "Nmos m1: Net x",
            "port vdd: .pos = (2, 13); .align = North",
        };
        for (String statement : statements) {
            // the trailing sibling line keeps end-of-file from masking
            // runaway suite parsing
            String source = "cell C:\n    viewgen v -> Schematic:\n        "
                + statement + "\n        pass\n";
            PsiFile psi = myFixture.configureByText("case.ord", source);
            Collection<PsiErrorElement> errors =
                PsiTreeUtil.findChildrenOfType(psi, PsiErrorElement.class);
            assertTrue("parse errors for: " + statement, errors.isEmpty());
        }
    }

    /**
     * simple_stmt in ord.lark chains small statements with ';' in any mix
     * of ORD and Python statements. Ellipsis must stay with the Python
     * parser (the local attribute override must not claim its first dot).
     */
    public void testSemicolonChainsAndEllipsis() {
        String[] statements = {
            "Net x; Net y",
            "net a; net b",
            "path p1; net n1, n2",
            "! .w == 1; ! .l == 2",
            "Net x; y = 5",
            "y = 5; Net x",
            "x = ...",
            ".pos = ...",
            "...",
        };
        for (String statement : statements) {
            String source = "cell C:\n    viewgen v -> Schematic:\n        "
                + statement + "\n        pass\n";
            PsiFile psi = myFixture.configureByText("case.ord", source);
            Collection<PsiErrorElement> errors =
                PsiTreeUtil.findChildrenOfType(psi, PsiErrorElement.class);
            assertTrue("parse errors for: " + statement, errors.isEmpty());
        }
    }

    /**
     * Decorated cell and viewgen definitions (the decorated rule in
     * ord.lark). A decorated plain function must stay Python.
     */
    public void testDecoratedDefinitions() {
        String[] sources = {
            "cell C:\n    @generate(auto_refresh=False)\n    viewgen v -> Schematic:\n        pass\n",
            "@register\ncell D:\n    pass\n",
            "@functools.cache\ndef f():\n    pass\n",
        };
        for (String source : sources) {
            PsiFile psi = myFixture.configureByText("case.ord", source);
            Collection<PsiErrorElement> errors =
                PsiTreeUtil.findChildrenOfType(psi, PsiErrorElement.class);
            assertTrue("parse errors for:\n" + source, errors.isEmpty());
        }
    }

    /**
     * Soft keywords used as plain names must stay ordinary Python (same
     * negatives as in support/editors/tests/test_editor_grammars.py).
     */
    public void testSoftKeywordNegatives() {
        String[] statements = {
            "cell = 5", "viewgen = f()", "net = row[i]", "path = \"/tmp\"",
            "match point:\n    case Point(x=0):\n        pass", "print(x)",
        };
        for (String statement : statements) {
            PsiFile psi = myFixture.configureByText("case.ord", statement + "\n");
            Collection<PsiErrorElement> errors =
                PsiTreeUtil.findChildrenOfType(psi, PsiErrorElement.class);
            assertTrue("parse errors for: " + statement, errors.isEmpty());
            psi.accept(new PsiRecursiveElementWalkingVisitor() {
                @Override
                public void visitElement(@NotNull PsiElement element) {
                    assertFalse("ORD element in plain Python: " + statement,
                        element.getNode() != null
                            && element.getNode().getElementType().toString().startsWith("ORD_"));
                    super.visitElement(element);
                }
            });
        }
    }

    /**
     * ORD nodes live in the Python dialect token sets, so Python PSI may
     * cast them to PyStatement/PyExpression. Regression test for the stub
     * builder ClassCastException on `.orientation *= MY` in
     * vco_pseudodiff.ord, where PyAstAugAssignmentStatement.getTarget cast
     * the ORD local attribute target.
     */
    public void testOrdElementsSatisfyPythonPsiCasts() {
        String source = "@register\n"
            + "cell C:\n"
            + "    @generate\n"
            + "    viewgen v -> Schematic:\n"
            + "        net vdd, ring.vx\n"
            + "        path ctr[0]\n"
            + "        Nmos m1:\n"
            + "            .orientation *= MY\n"
            + "        Nmos m2, m3\n"
            + "        ! .pos == (0, 0)\n";
        PsiFile psi = myFixture.configureByText("case.ord", source);
        assertEmpty(PsiTreeUtil.findChildrenOfType(psi, PsiErrorElement.class));

        // the exact navigation the stub indexer crashed on
        PyAugAssignmentStatement augAssignment =
            PsiTreeUtil.findChildOfType(psi, PyAugAssignmentStatement.class);
        assertNotNull(augAssignment);
        assertInstanceOf(augAssignment.getTarget(),
            OrdParserDefinition.OrdExpressionPsiElement.class);

        // every ORD node must satisfy the casts its token set entitles
        TokenSet statements = PythonDialectsTokenSetProvider.getInstance().getStatementTokens();
        TokenSet expressions = PythonDialectsTokenSetProvider.getInstance().getExpressionTokens();
        List<String> seen = new ArrayList<>();
        psi.accept(new PsiRecursiveElementWalkingVisitor() {
            @Override
            public void visitElement(@NotNull PsiElement element) {
                IElementType type = element.getNode().getElementType();
                if (type.toString().startsWith("ORD_")) {
                    seen.add(type.toString());
                    if (statements.contains(type)) {
                        assertInstanceOf(element, PyStatement.class);
                    }
                    if (expressions.contains(type)) {
                        assertInstanceOf(element, PyExpression.class);
                    }
                }
                super.visitElement(element);
            }
        });
        for (IElementType type : statements.getTypes()) {
            if (type.toString().startsWith("ORD_")) {
                assertTrue("construct not exercised: " + type, seen.contains(type.toString()));
            }
        }
        assertTrue("construct not exercised: ORD_LOCAL_ATTRIBUTE",
            seen.contains("ORD_LOCAL_ATTRIBUTE"));
    }

    /**
     * The ORD PSI extends PyElementImpl, and PyBaseElementImpl.getLanguage()
     * hardcodes Python, so ORD elements report Python rather than ORD. This
     * is why OrdAnnotator is registered for the Python language: registered
     * for ORD it would never be called and nothing ORD-specific would be
     * highlighted.
     */
    public void testOrdElementsReportPythonLanguage() {
        PsiFile psi = myFixture.configureByText("case.ord",
            "cell C:\n    viewgen v -> Schematic:\n        Nmos m1: .pos = (0, 0)\n");
        PsiElement cellDefinition = PsiTreeUtil.findChildOfType(
            psi, OrdParserDefinition.OrdStatementPsiElement.class);
        assertNotNull(cellDefinition);
        assertEquals(PythonLanguage.getInstance(), cellDefinition.getLanguage());
    }

    /**
     * ORD keywords are soft keywords that reach the lexer as identifiers,
     * so they can only be colored on the PSI by OrdAnnotator. Without it
     * only plain Python tokens are highlighted in .ord files.
     */
    public void testOrdConstructsAreHighlighted() {
        String source = "cell Nand:\n"
            + "    viewgen schematic -> Schematic:\n"
            + "        output y: .align=East\n"
            + "        net net_conn\n"
            + "        Nmos n1: .$w=1u; .d -- net_conn\n";
        myFixture.configureByText("case.ord", source);
        List<HighlightInfo> infos = myFixture.doHighlighting();
        // the constructs no lexer-based highlighting can reach
        assertHighlighted(infos, source, "cell");
        assertHighlighted(infos, source, "Nand");
        assertHighlighted(infos, source, "viewgen");
        assertHighlighted(infos, source, "schematic");
        assertHighlighted(infos, source, "output");
        assertHighlighted(infos, source, "net ");
        assertHighlighted(infos, source, "Nmos");
        assertHighlighted(infos, source, "align");
        assertHighlighted(infos, source, "$w");
    }

    /**
     * Python semantic inspections misfire on ORD constructs by design
     * (names bound by node statements are invisible to Python scope
     * analysis and connections are expression statements), so they are
     * suppressed inside .ord files and only there.
     */
    public void testPythonInspectionsSuppressedInOrdFiles() {
        myFixture.enableInspections(
            new PyUnresolvedReferencesInspection(), new PyStatementEffectInspection());
        myFixture.configureByText("case.ord",
            "cell C:\n    viewgen v -> Schematic:\n        Nmos m1\n        m1.d -- m1.g\n");
        assertEmpty(myFixture.doHighlighting(HighlightSeverity.WEAK_WARNING));
        // plain Python files must keep both inspections
        myFixture.configureByText("case.py", "undefined_reference\n");
        assertNotEmpty(myFixture.doHighlighting(HighlightSeverity.WEAK_WARNING));
    }

    private static void assertHighlighted(List<HighlightInfo> infos, String source, String text) {
        int start = source.indexOf(text);
        assertTrue("not in the test source: " + text, start >= 0);
        int end = start + text.trim().length();
        for (HighlightInfo info : infos) {
            if (info.getStartOffset() == start && info.getEndOffset() == end) {
                return;
            }
        }
        fail("not highlighted: " + text);
    }

    private static Path findRepoRoot() {
        Path dir = Paths.get("").toAbsolutePath();
        while (dir != null) {
            if (Files.exists(dir.resolve("ordec/ord/ord.lark"))) {
                return dir;
            }
            dir = dir.getParent();
        }
        throw new IllegalStateException("ordec repository root not found above " + Paths.get("").toAbsolutePath());
    }
}
