// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

package org.ordec.intellij;

import com.intellij.lang.ASTNode;
import com.intellij.lang.PsiParser;
import com.intellij.lexer.Lexer;
import com.intellij.openapi.project.Project;
import com.intellij.psi.FileViewProvider;
import com.intellij.psi.PsiElement;
import com.intellij.psi.PsiFile;
import com.intellij.psi.tree.IElementType;
import com.intellij.psi.tree.IFileElementType;
import com.jetbrains.python.PythonParserDefinition;
import com.jetbrains.python.psi.PyElementType;
import com.jetbrains.python.psi.PyExpression;
import com.jetbrains.python.psi.PyFileElementType;
import com.jetbrains.python.psi.PyStatement;
import com.jetbrains.python.psi.impl.PyElementImpl;
import com.jetbrains.python.psi.impl.PyFileImpl;
import com.jetbrains.python.psi.types.PyType;
import com.jetbrains.python.psi.types.TypeEvalContext;
import org.jetbrains.annotations.NotNull;
import org.jetbrains.annotations.Nullable;

import javax.swing.Icon;

public final class OrdParserDefinition extends PythonParserDefinition {
    // subclassed because the Language-taking constructor is protected
    private static final class OrdFileElementType extends PyFileElementType {
        private OrdFileElementType() {
            super(OrdLanguage.INSTANCE);
        }

        // the stub serializer registry asserts unique ids, so a second file
        // element type must not inherit Python's "python.FILE"
        @Override
        public @NotNull String getExternalId() {
            return "ord.FILE";
        }

        // bump the offset on every ORD parser change so .ord stubs reindex
        // independently of the Python plugin's stub version
        @Override
        public int getStubVersion() {
            return super.getStubVersion() + 3;
        }
    }

    /**
     * PSI file for .ord sources. PyFileImpl hardcodes the Python file icon
     * in getIcon and the project view takes the icon from the PSI file, so
     * without this override .ord files show as Python files in the tree
     * while the editor tab shows the ORD icon from OrdFileType.
     */
    public static final class OrdFile extends PyFileImpl {
        public OrdFile(@NotNull FileViewProvider viewProvider) {
            super(viewProvider, OrdLanguage.INSTANCE);
        }

        @Override
        public Icon getIcon(int flags) {
            return OrdFileType.INSTANCE.getIcon();
        }
    }

    /**
     * OrdTokenSetContributor registers the ORD nodes in the Python dialect
     * token sets, so Python PSI code is entitled to cast them to
     * PyExpression or PyStatement wherever those token sets match, for
     * example PyAstAugAssignmentStatement.getTarget or
     * PyAstStatementList.getStatements. Generic wrapper PSI fails those
     * casts, seen as ClassCastException during stub indexing of .ord files.
     */
    public static final class OrdExpressionPsiElement extends PyElementImpl
            implements PyExpression {
        public OrdExpressionPsiElement(@NotNull ASTNode node) {
            super(node);
        }

        @Override
        public @Nullable PyType getType(@NotNull TypeEvalContext context,
                @NotNull TypeEvalContext.Key key) {
            // ORD node references have no Python type
            return null;
        }
    }

    public static final class OrdStatementPsiElement extends PyElementImpl
            implements PyStatement {
        public OrdStatementPsiElement(@NotNull ASTNode node) {
            super(node);
        }
    }

    private static final IFileElementType FILE = new OrdFileElementType();

    @Override
    public @NotNull Lexer createLexer(Project project) {
        return new OrdLexer();
    }

    @Override
    public @NotNull PsiParser createParser(Project project) {
        return new OrdParser();
    }

    @Override
    public @NotNull IFileElementType getFileNodeType() {
        return FILE;
    }

    @Override
    public @NotNull PsiFile createFile(@NotNull FileViewProvider viewProvider) {
        return new OrdFile(viewProvider);
    }

    @Override
    public @NotNull PsiElement createElement(@NotNull ASTNode node) {
        IElementType type = node.getElementType();
        if (type == OrdElementTypes.LOCAL_ATTRIBUTE || type == OrdElementTypes.CONTEXT_TARGET) {
            return new OrdExpressionPsiElement(node);
        }
        if (!(type instanceof PyElementType)) {
            return new OrdStatementPsiElement(node);
        }
        return super.createElement(node);
    }
}
