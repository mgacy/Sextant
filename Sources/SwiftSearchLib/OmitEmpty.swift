//
//  OmitEmpty.swift
//  Sextant
//
//  Created by Mathew Gacy on 3/8/26.
//  Copyright © 2026 Mathew Gacy. All rights reserved.
//

import Foundation

/// A type that has a meaningful empty state.
public protocol EmptyInitializable: Equatable {
    /// The canonical empty value for this type.
    static var empty: Self { get }
    /// Whether this value is empty.
    var isEmpty: Bool { get }
}

// MARK: - EmptyInitializable Conformances

extension Array: EmptyInitializable where Element: Equatable {
    public static var empty: [Element] { [] }
}

extension String: EmptyInitializable {
    public static var empty: String { "" }
}

// MARK: - OmitEmpty Property Wrapper

/// A property wrapper that omits empty values during encoding and decodes missing keys as empty defaults.
///
/// Use `@OmitEmpty` on properties whose empty state should be elided from JSON output:
/// ```swift
/// struct Example: Codable {
///     let name: String
///     @OmitEmpty var tags: [String]
/// }
/// ```
/// When `tags` is empty, the key is omitted from the encoded JSON.
/// When decoding JSON that lacks the `tags` key, the property decodes to `[]`.
@propertyWrapper
public struct OmitEmpty<T: EmptyInitializable & Codable & Sendable>: Sendable {
    public var wrappedValue: T

    public init(wrappedValue: T) {
        self.wrappedValue = wrappedValue
    }
}

// MARK: - Equatable

extension OmitEmpty: Equatable {
    public static func == (lhs: OmitEmpty, rhs: OmitEmpty) -> Bool {
        lhs.wrappedValue == rhs.wrappedValue
    }
}

// MARK: - Codable

extension OmitEmpty: Codable {
    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        wrappedValue = try container.decode(T.self)
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        try container.encode(wrappedValue)
    }
}

// MARK: - KeyedEncodingContainer Overloads

public extension KeyedEncodingContainer {
    /// Skips the key entirely when the wrapped value is empty.
    mutating func encode<T: EmptyInitializable & Codable & Sendable>(
        _ value: OmitEmpty<T>,
        forKey key: Key
    ) throws {
        if !value.wrappedValue.isEmpty {
            try encode(value.wrappedValue, forKey: key)
        }
    }
}

// MARK: - KeyedDecodingContainer Overloads

public extension KeyedDecodingContainer {
    /// Decodes the wrapped value if present, otherwise falls back to `T.empty`.
    func decode<T: EmptyInitializable & Codable & Sendable>(
        _ type: OmitEmpty<T>.Type,
        forKey key: Key
    ) throws -> OmitEmpty<T> {
        if let value = try decodeIfPresent(T.self, forKey: key) {
            return OmitEmpty(wrappedValue: value)
        }
        return OmitEmpty(wrappedValue: T.empty)
    }
}
