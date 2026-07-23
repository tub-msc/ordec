// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

package org.ordec.intellij;

import com.intellij.psi.PsiElement;
import com.intellij.psi.PsiErrorElement;
import com.intellij.psi.PsiFile;
import com.intellij.psi.PsiRecursiveElementWalkingVisitor;
import com.intellij.psi.util.PsiTreeUtil;
import com.intellij.testFramework.fixtures.BasePlatformTestCase;
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
 * The dialect's exit criterion, mirroring tests/test_editor_grammars.py:
 * every .ord file in the repository must parse without PSI error elements.
 */
public class OrdDialectParsingTest extends BasePlatformTestCase {
    public void testRepositoryOrdFilesParse() throws IOException {
        Path repoRoot = findRepoRoot();
        List<Path> ordFiles = new ArrayList<>();
        for (String dir : new String[]{"ordec", "tests"}) {
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
     * The synthetic positives from tests/test_editor_grammars.py: kind and
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
            // the trailing sibling line ensures the one-line suite really
            // ends at its line, end-of-file must not mask runaway parsing
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
     * ord.lark); a decorated plain function must stay Python.
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
     * Soft keywords used as plain names must stay ordinary Python, same
     * negatives as in tests/test_editor_grammars.py.
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
