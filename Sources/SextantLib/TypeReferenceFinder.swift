//
//  TypeReferenceFinder.swift
//  Sextant
//
//  Created by Mathew Gacy on 3/15/26.
//

import SwiftSyntax

/// Walks a swift-syntax tree to find type-position references to a given name.
///
/// This is an implementation detail of `FileParser.findReferences` and should not be used directly.
/// It visits `IdentifierTypeSyntax` and `MemberTypeSyntax` nodes in declaration-level type positions
/// (inheritance clauses, parameter types, return types, type annotations, typealias targets, and
/// generic constraints) while skipping function bodies, variable initializers, computed property
/// bodies, and import statements.
final class TypeReferenceFinder: SyntaxVisitor {

    // MARK: - Properties

    /// The type name to search for.
    private let searchName: String

    /// The file path to associate with matches.
    private let file: String

    /// Converter for resolving source locations.
    private let converter: SourceLocationConverter

    /// The accumulated matches found during the walk.
    private(set) var matches: [ReferenceMatch] = []

    /// Stack of declaration contexts, pushed on visit and popped on visitPost.
    private var contextStack: [DeclarationContext] = []

    // MARK: - Types

    /// Tracks the containing declaration for a matched type reference.
    private struct DeclarationContext {
        let name: String
        let kind: SymbolKind
        let parentChain: String
        let fullDeclaration: String
        let line: Int
    }

    // MARK: - Initialization

    /// Creates a type reference finder.
    ///
    /// - Parameters:
    ///   - name: The type name to search for (exact match against identifier tokens).
    ///   - file: The file path to associate with matches.
    ///   - converter: Converter for resolving source locations.
    init(name: String, file: String, converter: SourceLocationConverter) {
        self.searchName = name
        self.file = file
        self.converter = converter
        super.init(viewMode: .sourceAccurate)
    }

    // MARK: - Skip Forbidden Subtrees

    override func visit(_ node: CodeBlockSyntax) -> SyntaxVisitorContinueKind {
        .skipChildren
    }

    override func visit(_ node: AccessorBlockSyntax) -> SyntaxVisitorContinueKind {
        .skipChildren
    }

    override func visit(_ node: InitializerClauseSyntax) -> SyntaxVisitorContinueKind {
        .skipChildren
    }

    override func visit(_ node: ImportDeclSyntax) -> SyntaxVisitorContinueKind {
        .skipChildren
    }

    // MARK: - Declaration Context Tracking

    override func visit(_ node: StructDeclSyntax) -> SyntaxVisitorContinueKind {
        pushContext(name: node.name.text, kind: .struct, node: node)
        return .visitChildren
    }

    override func visitPost(_ node: StructDeclSyntax) {
        popContext()
    }

    override func visit(_ node: ClassDeclSyntax) -> SyntaxVisitorContinueKind {
        pushContext(name: node.name.text, kind: .class, node: node)
        return .visitChildren
    }

    override func visitPost(_ node: ClassDeclSyntax) {
        popContext()
    }

    override func visit(_ node: EnumDeclSyntax) -> SyntaxVisitorContinueKind {
        pushContext(name: node.name.text, kind: .enum, node: node)
        return .visitChildren
    }

    override func visitPost(_ node: EnumDeclSyntax) {
        popContext()
    }

    override func visit(_ node: ProtocolDeclSyntax) -> SyntaxVisitorContinueKind {
        pushContext(name: node.name.text, kind: .protocol, node: node)
        return .visitChildren
    }

    override func visitPost(_ node: ProtocolDeclSyntax) {
        popContext()
    }

    override func visit(_ node: ActorDeclSyntax) -> SyntaxVisitorContinueKind {
        pushContext(name: node.name.text, kind: .actor, node: node)
        return .visitChildren
    }

    override func visitPost(_ node: ActorDeclSyntax) {
        popContext()
    }

    override func visit(_ node: ExtensionDeclSyntax) -> SyntaxVisitorContinueKind {
        pushContext(name: node.extendedType.trimmedDescription, kind: .extension, node: node)
        return .visitChildren
    }

    override func visitPost(_ node: ExtensionDeclSyntax) {
        popContext()
    }

    override func visit(_ node: FunctionDeclSyntax) -> SyntaxVisitorContinueKind {
        pushContext(name: node.name.text, kind: .function, node: node)
        return .visitChildren
    }

    override func visitPost(_ node: FunctionDeclSyntax) {
        popContext()
    }

    override func visit(_ node: VariableDeclSyntax) -> SyntaxVisitorContinueKind {
        let name = node.bindings.first?
            .pattern.as(IdentifierPatternSyntax.self)?
            .identifier.text ?? "<unknown>"
        pushContext(name: name, kind: .variable, node: node)
        return .visitChildren
    }

    override func visitPost(_ node: VariableDeclSyntax) {
        popContext()
    }

    override func visit(_ node: InitializerDeclSyntax) -> SyntaxVisitorContinueKind {
        pushContext(name: "init", kind: .initializer, node: node)
        return .visitChildren
    }

    override func visitPost(_ node: InitializerDeclSyntax) {
        popContext()
    }

    override func visit(_ node: TypeAliasDeclSyntax) -> SyntaxVisitorContinueKind {
        pushContext(name: node.name.text, kind: .typealias, node: node)
        return .visitChildren
    }

    override func visitPost(_ node: TypeAliasDeclSyntax) {
        popContext()
    }

    override func visit(_ node: EnumCaseElementSyntax) -> SyntaxVisitorContinueKind {
        pushContext(name: node.name.text, kind: .case, node: node)
        return .visitChildren
    }

    override func visitPost(_ node: EnumCaseElementSyntax) {
        popContext()
    }

    // MARK: - Type Reference Matching

    override func visit(_ node: IdentifierTypeSyntax) -> SyntaxVisitorContinueKind {
        guard node.name.text == searchName else {
            return .visitChildren
        }

        // Skip if this node is inside a MemberTypeSyntax -- MemberTypeSyntax visit handles it
        if node.parent?.is(MemberTypeSyntax.self) == true {
            return .visitChildren
        }

        guard let position = classifyPosition(of: Syntax(node)) else {
            return .visitChildren
        }

        recordMatch(name: searchName, position: position)
        return .visitChildren
    }

    override func visit(_ node: MemberTypeSyntax) -> SyntaxVisitorContinueKind {
        // Check both the base type name and the member name
        let baseText = node.baseType.trimmedDescription
        let memberText = node.name.text
        let fullText = node.trimmedDescription

        let baseMatches = baseText == searchName
        let memberMatches = memberText == searchName
        let fullMatches = fullText == searchName

        guard baseMatches || memberMatches || fullMatches else {
            return .visitChildren
        }

        guard let position = classifyPosition(of: Syntax(node)) else {
            return .visitChildren
        }

        recordMatch(name: fullText, position: position)
        // Continue into children so that types in generic arguments are visited
        // (e.g., searching "Baz" finds it in `Foo.Bar<Baz>`). This means
        // `Foo.Bar<Foo>` can produce two matches when searching "Foo" — one for
        // the member type and one for the generic argument.
        return .visitChildren
    }
}

// MARK: - Position Classification

private extension TypeReferenceFinder {

    /// Classifies the reference position by walking up the parent chain from the type node.
    ///
    /// - Parameter node: The syntax node to classify.
    /// - Returns: The reference position, or `nil` if the node is not in a recognized declaration-level position.
    func classifyPosition(of node: Syntax) -> ReferencePosition? {
        var current: Syntax? = node.parent
        while let parent = current {
            if parent.is(InheritanceClauseSyntax.self) {
                return .inheritance
            }
            if parent.is(EnumCaseParameterSyntax.self) {
                return .associatedValue
            }
            if parent.is(FunctionParameterSyntax.self) {
                return .parameterType
            }
            if parent.is(ReturnClauseSyntax.self) {
                return .returnType
            }
            if parent.is(TypeAnnotationSyntax.self) {
                return .typeAnnotation
            }
            if parent.is(GenericParameterSyntax.self) {
                return .genericConstraint
            }
            if parent.is(TypeAliasDeclSyntax.self) {
                // Catches the RHS type (e.g., `typealias Alias = TargetType`). Inline generic
                // parameter constraints (e.g., `<T: Foo>`) are classified as .genericConstraint
                // by the GenericParameterSyntax check above; `where` constraints are classified
                // as .genericConstraint by the GenericWhereClauseSyntax check below.
                return .typealiasTarget
            }
            if parent.is(GenericWhereClauseSyntax.self) {
                return .genericConstraint
            }

            // Stop walking at declaration boundaries to avoid misclassification
            if isDeclarationBoundary(parent) {
                return nil
            }

            current = parent.parent
        }
        return nil
    }

    /// Checks if a syntax node represents a declaration boundary that should stop the parent walk.
    ///
    /// - Parameter node: The syntax node to check.
    /// - Returns: `true` if the node is a declaration boundary.
    func isDeclarationBoundary(_ node: Syntax) -> Bool {
        node.is(CodeBlockSyntax.self)
            || node.is(AccessorBlockSyntax.self)
            || node.is(InitializerClauseSyntax.self)
            || node.is(MemberBlockSyntax.self)
    }
}

// MARK: - Context Stack

private extension TypeReferenceFinder {

    /// Pushes a new declaration context onto the stack.
    ///
    /// - Parameters:
    ///   - name: The declaration name.
    ///   - kind: The declaration kind.
    ///   - node: The syntax node for computing line number and full declaration.
    func pushContext(name: String, kind: SymbolKind, node: some SyntaxProtocol) {
        let parentChain: String
        if let top = contextStack.last {
            parentChain = top.parentChain.isEmpty
                ? top.name
                : "\(top.parentChain).\(top.name)"
        } else {
            parentChain = ""
        }

        let line = node.startLocation(converter: converter).line
        let fullDeclaration = truncatedDeclaration(for: node)

        contextStack.append(DeclarationContext(
            name: name,
            kind: kind,
            parentChain: parentChain,
            fullDeclaration: fullDeclaration,
            line: line
        ))
    }

    /// Pops the top declaration context from the stack.
    func popContext() {
        guard !contextStack.isEmpty else { return }
        contextStack.removeLast()
    }

    /// Records a match using the current declaration context.
    ///
    /// - Parameters:
    ///   - name: The matched type name text.
    ///   - position: The classified reference position.
    func recordMatch(name: String, position: ReferencePosition) {
        guard let context = contextStack.last else { return }
        matches.append(ReferenceMatch(
            name: name,
            position: position,
            declarationName: context.name,
            declarationKind: context.kind,
            parentName: context.parentChain,
            fullDeclaration: context.fullDeclaration,
            file: file,
            line: context.line
        ))
    }

    /// Generates a truncated single-line declaration string for context.
    ///
    /// Trims the declaration at the first `{` if present, providing a concise representation
    /// of the declaration signature without the body.
    ///
    /// - Parameter node: The syntax node to describe.
    /// - Returns: A trimmed declaration string.
    func truncatedDeclaration(for node: some SyntaxProtocol) -> String {
        let description = node.trimmedDescription
        if let braceIndex = description.firstIndex(of: "{") {
            return String(description[..<braceIndex])
                .trimmingCharacters(in: .whitespacesAndNewlines)
        }
        return description
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
