// swift-tools-version: 6.2
// The swift-tools-version declares the minimum version of Swift required to build this package.

import PackageDescription

let package = Package(
    name: "Sextant",
    platforms: [
        .macOS(.v14)
    ],
    products: [
    ],
    dependencies: [
        .package(url: "https://github.com/CheekyGhost-Labs/SyntaxSparrow", from: "6.1.0"),
        .package(url: "https://github.com/apple/swift-argument-parser", from: "1.5.0"),
        .package(url: "https://github.com/mgacy/swift-version-file-plugin.git", from: "0.2.0"),
        .package(url: "https://github.com/swiftlang/swift-syntax", from: "601.0.1")
    ],
    targets: [
    ]
)
