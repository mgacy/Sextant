//
//  StructuralQuery.swift
//  Sextant
//
//  Created by Mathew Gacy on 3/8/26.
//  Copyright © 2026 Mathew Gacy. All rights reserved.
//

import Foundation

/// Represents a matched enum case with contextual information.
public struct EnumCaseMatch: Codable, Equatable, Sendable {

    /// The name of the parent enum.
    public let enumName: String

    /// The case name.
    public let caseName: String

    /// The associated value types (e.g., ["Result<Success, Failure>"]).
    public let associatedValues: [String]

    /// The full serialized case declaration (e.g., "fetched(Result<Success, Failure>)").
    public let fullDeclaration: String

    /// The file where this case is declared.
    public let file: String

    /// The 1-based line number of the case declaration.
    public let line: Int

    public init(
        enumName: String,
        caseName: String,
        associatedValues: [String],
        fullDeclaration: String,
        file: String,
        line: Int
    ) {
        self.enumName = enumName
        self.caseName = caseName
        self.associatedValues = associatedValues
        self.fullDeclaration = fullDeclaration
        self.file = file
        self.line = line
    }
}

/// Provides structural query operations over parsed file overviews.
///
/// Operations include:
/// - Enum case search by regex pattern against the full serialized declaration
/// - Symbol filtering by kind
public struct StructuralQuery: Sendable {

    public enum Error: Swift.Error, LocalizedError, Sendable {
        case invalidPattern(String, underlying: any Swift.Error)

        public var errorDescription: String? {
            switch self {
            case let .invalidPattern(pattern, underlying):
                "Invalid regex pattern: \(pattern) (\(underlying.localizedDescription))"
            }
        }
    }

    public init() {}

    // MARK: - Enum Case Search

    /// Finds all enum cases matching a regex pattern against their full serialized declaration.
    ///
    /// The pattern is matched against the full declaration string, e.g.,
    /// `fetched(Result<Success, Failure>)`. This means `--pattern fetched` matches by case name
    /// substring, and `--pattern "Result<"` matches by associated value type.
    ///
    /// - Parameters:
    ///   - pattern: A regex pattern to match against the full serialized case declaration.
    ///   - overviews: The file overviews to search.
    /// - Returns: An array of matching enum case entries.
    /// - Throws: `StructuralQuery.Error.invalidPattern` if the regex pattern is invalid.
    public func findEnumCases(matching pattern: String, in overviews: [FileOverview]) throws(Error) -> [EnumCaseMatch] {
        let regex: Regex<AnyRegexOutput>
        do {
            regex = try Regex(pattern)
        } catch {
            throw .invalidPattern(pattern, underlying: error)
        }

        var results: [EnumCaseMatch] = []

        for overview in overviews {
            collectEnumCases(
                from: overview.declarations,
                file: overview.file,
                regex: regex,
                results: &results
            )
        }

        return results
    }

    /// Finds all enum cases across the given overviews (no pattern filter).
    ///
    /// - Parameter overviews: The file overviews to search.
    /// - Returns: An array of all enum case entries.
    public func allEnumCases(in overviews: [FileOverview]) -> [EnumCaseMatch] {
        var results: [EnumCaseMatch] = []

        for overview in overviews {
            collectEnumCases(
                from: overview.declarations,
                file: overview.file,
                regex: nil,
                results: &results
            )
        }

        return results
    }

    // MARK: - Symbol Filtering

    /// Filters declarations by kind across all overviews (including nested declarations).
    ///
    /// - Parameters:
    ///   - kind: The `SymbolKind` to filter by.
    ///   - overviews: The file overviews to search.
    /// - Returns: An array of `SymbolEntry` matching the given kind.
    public func findSymbols(ofKind kind: SymbolKind, in overviews: [FileOverview]) -> [SymbolEntry] {
        var results: [SymbolEntry] = []

        for overview in overviews {
            collectSymbols(
                ofKind: kind,
                from: overview.declarations,
                file: overview.file,
                results: &results
            )
        }

        return results
    }

    // MARK: - Private Helpers

    private func collectEnumCases(
        from declarations: [Declaration],
        file: String,
        regex: Regex<AnyRegexOutput>?,
        results: inout [EnumCaseMatch]
    ) {
        for decl in declarations {
            if decl.kind == .enum {
                // Look for cases inside this enum
                for child in decl.children where child.kind == .case {
                    let matches: Bool
                    if let regex {
                        matches = child.fullDeclaration.contains(regex)
                    } else {
                        matches = true
                    }

                    if matches {
                        results.append(EnumCaseMatch(
                            enumName: decl.name,
                            caseName: child.name,
                            associatedValues: child.associatedValues,
                            fullDeclaration: child.fullDeclaration,
                            file: file,
                            line: child.line
                        ))
                    }
                }

                // Recurse into nested types within the enum
                collectEnumCases(
                    from: decl.children.filter { $0.kind != .case },
                    file: file,
                    regex: regex,
                    results: &results
                )
            } else {
                // Recurse into nested types within structs, classes, etc.
                collectEnumCases(
                    from: decl.children,
                    file: file,
                    regex: regex,
                    results: &results
                )
            }
        }
    }

    private func collectSymbols(
        ofKind kind: SymbolKind,
        from declarations: [Declaration],
        file: String,
        parentName: String = "",
        results: inout [SymbolEntry]
    ) {
        for decl in declarations {
            if decl.kind == kind {
                results.append(SymbolEntry(
                    name: decl.name,
                    kind: decl.kind,
                    file: file,
                    line: decl.line,
                    parentName: parentName,
                    fullDeclaration: decl.fullDeclaration,
                    attributes: decl.attributes,
                    conformances: decl.conformances,
                    associatedValues: decl.associatedValues
                ))
            }

            // Recurse into children
            collectSymbols(
                ofKind: kind,
                from: decl.children,
                file: file,
                parentName: parentName.isEmpty ? decl.name : "\(parentName).\(decl.name)",
                results: &results
            )
        }
    }
}
