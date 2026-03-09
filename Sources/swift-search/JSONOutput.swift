//
//  JSONOutput.swift
//  Sextant
//
//  Created by Mathew Gacy on 3/8/26.
//  Copyright © 2026 Mathew Gacy. All rights reserved.
//

import Foundation

/// Encodes a value as JSON and prints it to stdout.
///
/// - Parameters:
///   - value: The value to encode.
///   - pretty: If `true`, pretty-prints the JSON output. Defaults to `false`.
/// - Throws: `EncodingError` if encoding fails.
func printJSON<T: Encodable>(_ value: T, pretty: Bool = false) throws {
    let encoder = JSONEncoder()
    encoder.outputFormatting = pretty ? [.prettyPrinted, .sortedKeys] : [.sortedKeys]
    let data = try encoder.encode(value)
    print(String(decoding: data, as: UTF8.self))
}
