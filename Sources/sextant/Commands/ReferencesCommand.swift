//
//  ReferencesCommand.swift
//  Sextant
//
//  Created by Mathew Gacy on 3/15/26.
//

import ArgumentParser
import SextantLib

/// Searches for type references in declaration-level positions.
///
/// Finds where a type name appears in inheritance clauses, parameter types, return types,
/// type annotations, typealias targets, and generic constraints. Does not match inside
/// function bodies, variable initializers, computed property bodies, or import statements.
struct ReferencesCommand: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "references",
        abstract: "Find declaration-level type references"
    )

    @Argument(help: "Type name to search for")
    var name: String

    @Option(name: .long, help: "Path to scan (default: current directory)")
    var path: String = "."

    @Option(name: .long, help: "Filter by reference position (inheritance, associatedValue, parameterType, returnType, typeAnnotation, typealiasTarget, genericConstraint)")
    var position: ReferencePosition?

    @OptionGroup var output: OutputOptions

    func run() async throws {
        var results = try await scanAndFindReferences(
            to: name,
            at: path,
            relativeTo: output.absolute ? nil : path
        )

        if let position {
            results = results.filter { $0.position == position }
        }

        try printJSON(results, pretty: output.pretty)
    }
}
