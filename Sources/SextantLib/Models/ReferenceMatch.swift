//
//  ReferenceMatch.swift
//  Sextant
//
//  Created by Mathew Gacy on 3/15/26.
//

/// Where in a declaration the type reference appears.
public enum ReferencePosition: String, Codable, Equatable, Sendable {
    case inheritance
    case associatedValue
    case parameterType
    case returnType
    case typeAnnotation
    case typealiasTarget
    case genericConstraint
}

/// A type name found in a declaration-level type position.
public struct ReferenceMatch: Codable, Equatable, Sendable {

    /// The referenced type name as it appears in source (e.g., "ItemReducer" or "ItemReducer.State").
    public let name: String

    /// Where in the declaration the reference appears.
    public let position: ReferencePosition

    /// Name of the immediately containing declaration.
    public let declarationName: String

    /// Kind of the immediately containing declaration (e.g., `.case` for an enum case, `.function` for a method).
    public let declarationKind: SymbolKind

    /// Parent chain for nested declarations (e.g., "ListReducer.State"). Empty for top-level.
    @OmitEmpty public var parentName: String

    /// The full serialized declaration containing the reference (e.g., "case item(ItemReducer)").
    @OmitEmpty public var fullDeclaration: String

    /// The file where this reference appears.
    public let file: String

    /// The 1-based line number of the containing declaration.
    public let line: Int

    /// Creates a reference match.
    ///
    /// - Parameters:
    ///   - name: The referenced type name.
    ///   - position: Where in the declaration the reference appears.
    ///   - declarationName: Name of the containing declaration.
    ///   - declarationKind: Kind of the containing declaration.
    ///   - parentName: Parent chain for nested declarations.
    ///   - fullDeclaration: The full serialized containing declaration.
    ///   - file: The file where this reference appears.
    ///   - line: The 1-based line number of the containing declaration.
    public init(
        name: String,
        position: ReferencePosition,
        declarationName: String,
        declarationKind: SymbolKind,
        parentName: String = "",
        fullDeclaration: String = "",
        file: String,
        line: Int
    ) {
        self.name = name
        self.position = position
        self.declarationName = declarationName
        self.declarationKind = declarationKind
        self.parentName = parentName
        self.fullDeclaration = fullDeclaration
        self.file = file
        self.line = line
    }
}

/// The result of searching for type references across multiple Swift files concurrently.
///
/// Contains successfully found reference matches and any file-level failures.
public struct ReferenceResult: Sendable {

    /// All reference matches found, sorted by file path.
    public let matches: [ReferenceMatch]

    /// Files that failed to parse, sorted by file path.
    public let failures: [ParseFailure]

    /// The number of files that were successfully scanned.
    public let scannedFileCount: Int

    /// The total number of files that were attempted.
    public var totalCount: Int { scannedFileCount + failures.count }

    /// Whether all attempted files failed to parse.
    public var allFailed: Bool { scannedFileCount == 0 && !failures.isEmpty }

    /// Creates a reference result.
    ///
    /// - Parameters:
    ///   - matches: All reference matches found.
    ///   - failures: Files that failed to parse with their errors.
    ///   - scannedFileCount: The number of files that were successfully scanned.
    public init(matches: [ReferenceMatch], failures: [ParseFailure], scannedFileCount: Int) {
        self.matches = matches
        self.failures = failures
        self.scannedFileCount = scannedFileCount
    }
}
