// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

package org.ordec.intellij;

import com.intellij.lang.ASTNode;
import com.intellij.lang.annotation.AnnotationHolder;
import com.intellij.lang.annotation.Annotator;
import com.intellij.lang.annotation.HighlightSeverity;
import com.intellij.openapi.editor.DefaultLanguageHighlighterColors;
import com.intellij.openapi.editor.colors.TextAttributesKey;
import com.intellij.psi.PsiElement;
import com.intellij.psi.tree.IElementType;
import com.intellij.psi.tree.TokenSet;
import com.jetbrains.python.PyTokenTypes;
import com.jetbrains.python.highlighting.PyHighlighter;
import com.jetbrains.python.psi.PyCallExpression;
import com.jetbrains.python.psi.PyExpression;
import com.jetbrains.python.psi.PyReferenceExpression;
import com.jetbrains.python.psi.PySubscriptionExpression;
import org.jetbrains.annotations.NotNull;

import java.util.Set;

/**
 * Highlighting for the ORD constructs, mirroring the captures in
 * support/editors/tree-sitter-ord/queries/highlights.scm. The ORD keywords
 * are soft keywords that reach the lexer as plain identifiers, so
 * lexer-based highlighting cannot color them and this runs on the PSI.
 *
 * Registered for the Python language, not for ORD: the ORD PSI extends
 * PyElementImpl, whose PyBaseElementImpl.getLanguage() hardcodes Python,
 * so annotators registered for ORD are never called for ORD elements.
 * Elements of other languages leave through the element type check below.
 */
public final class OrdAnnotator implements Annotator {
    private static final Set<String> SOFT_KEYWORDS =
        Set.of("cell", "viewgen", "net", "path", "anonymous");
    // directional pin kinds keep their traditional keyword look even
    // though they are ordinary names in the grammar
    private static final Set<String> PIN_KINDS =
        Set.of("input", "output", "inout", "port");
    private static final TokenSet IDENTIFIER_SET = TokenSet.create(PyTokenTypes.IDENTIFIER);

    @Override
    public void annotate(@NotNull PsiElement element, @NotNull AnnotationHolder holder) {
        // the Python-language registration means this runs for every Python
        // file too, so bail out before any per-element work there
        if (!(element.getContainingFile() instanceof OrdParserDefinition.OrdFile)) {
            return;
        }
        IElementType type = element.getNode().getElementType();
        if (type == OrdElementTypes.CELL_DEFINITION) {
            annotateHeader(element, holder, PyHighlighter.PY_CLASS_DEFINITION);
        } else if (type == OrdElementTypes.VIEWGEN_DEFINITION) {
            annotateHeader(element, holder, PyHighlighter.PY_FUNC_DEFINITION);
            // the return type after "->" is the first expression child
            annotateKind(element, holder, false);
        } else if (type == OrdElementTypes.PATH_NET_STATEMENT) {
            annotateLeadingKeyword(element, holder);
        } else if (type == OrdElementTypes.NODE_STATEMENT
                || type == OrdElementTypes.NODE_STATEMENT_NOBODY) {
            // the leading keyword can only be the optional "anonymous" prefix
            annotateLeadingKeyword(element, holder);
            annotateKind(element, holder, true);
        } else if (type == OrdElementTypes.LOCAL_ATTRIBUTE) {
            annotateParameterOrAttribute(element, holder);
        } else if (element instanceof PyExpression) {
            // qualified parameter access (t.$w), the leading-dot form is
            // covered by LOCAL_ATTRIBUTE above
            annotateParameterOrAttribute(element, holder);
        }
    }

    private static void mark(AnnotationHolder holder, ASTNode node, TextAttributesKey key) {
        holder.newSilentAnnotation(HighlightSeverity.INFORMATION)
            .range(node)
            .textAttributes(key)
            .create();
    }

    /**
     * Colors the name of a local attribute (.pos) or of a parameter access
     * ($l, merged into one identifier token by OrdLexer) as a field. For
     * qualified expressions this must not touch ordinary Python attribute
     * access, so only '$' names are colored there.
     */
    private static void annotateParameterOrAttribute(PsiElement element, AnnotationHolder holder) {
        ASTNode name = element.getNode().findChildByType(PyTokenTypes.IDENTIFIER);
        if (name == null) {
            return;
        }
        boolean isLocalAttribute =
            element.getNode().getElementType() == OrdElementTypes.LOCAL_ATTRIBUTE;
        if (isLocalAttribute || name.getText().startsWith("$")) {
            mark(holder, name, DefaultLanguageHighlighterColors.INSTANCE_FIELD);
        }
    }

    private static void annotateLeadingKeyword(PsiElement element, AnnotationHolder holder) {
        ASTNode first = element.getNode().getFirstChildNode();
        if (first != null && first.getElementType() == PyTokenTypes.IDENTIFIER
                && SOFT_KEYWORDS.contains(first.getText())) {
            mark(holder, first, PyHighlighter.PY_KEYWORD);
        }
    }

    // cell and viewgen headers: keyword token followed by the name token
    private static void annotateHeader(PsiElement element, AnnotationHolder holder,
            TextAttributesKey nameKey) {
        annotateLeadingKeyword(element, holder);
        ASTNode[] names = element.getNode().getChildren(IDENTIFIER_SET);
        if (names.length >= 2) {
            mark(holder, names[1], nameKey);
        }
    }

    /**
     * Colors the kind expression of a node statement (Nmos, lib.Inv,
     * Vdc(dc=1)) or the viewgen return type as a class reference, keeping
     * the color on the last name of qualified kinds like the tree-sitter
     * captures do. Bare directional pin kinds become keywords instead.
     */
    private static void annotateKind(PsiElement element, AnnotationHolder holder,
            boolean allowPinKeyword) {
        PyExpression kind = null;
        for (PsiElement child = element.getFirstChild(); child != null;
                child = child.getNextSibling()) {
            if (child instanceof PyExpression) {
                kind = (PyExpression) child;
                break;
            }
        }
        if (kind == null) {
            return;
        }
        PyExpression callee = kind;
        while (true) {
            if (callee instanceof PyCallExpression) {
                callee = ((PyCallExpression) callee).getCallee();
            } else if (callee instanceof PySubscriptionExpression) {
                // subscripted kinds like rows[0] r0:
                callee = ((PySubscriptionExpression) callee).getOperand();
            } else {
                break;
            }
            if (callee == null) {
                return;
            }
        }
        if (!(callee instanceof PyReferenceExpression)) {
            return;
        }
        PyReferenceExpression reference = (PyReferenceExpression) callee;
        ASTNode name = reference.getNameElement();
        if (name == null) {
            return;
        }
        if (allowPinKeyword && callee == kind && reference.getQualifier() == null
                && PIN_KINDS.contains(name.getText())) {
            mark(holder, name, PyHighlighter.PY_KEYWORD);
        } else {
            mark(holder, name, DefaultLanguageHighlighterColors.CLASS_REFERENCE);
        }
    }
}
