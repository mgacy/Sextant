// swift-tools-version: 6.2
// The swift-tools-version declares the minimum version of Swift required to build this package.

import PackageDescription

let package = Package(
    name: "Sextant",
    platforms: [
        .macOS(.v14)
    ],
    products: [
        .executable(name: "sextant", targets: ["sextant"]),
        .library(name: "SextantLib", targets: ["SextantLib"])
    ],
    dependencies: [
        .package(url: "https://github.com/apple/swift-argument-parser", from: "1.5.0"),
        .package(url: "https://github.com/mgacy/swift-version-file-plugin.git", from: "0.2.0"),
        .package(url: "https://github.com/swiftlang/swift-docc-plugin", from: "1.4.3"),
        .package(url: "https://github.com/swiftlang/swift-syntax", from: "602.0.0")
    ],
    targets: [
        .executableTarget(
            name: "sextant",
            dependencies: [
                "SextantLib",
                .product(name: "ArgumentParser", package: "swift-argument-parser")
            ]
        ),
        .target(
            name: "SextantLib",
            dependencies: [
                .product(name: "SwiftParser", package: "swift-syntax"),
                .product(name: "SwiftSyntax", package: "swift-syntax")
            ]
        ),
        .testTarget(
            name: "SextantTests",
            dependencies: ["SextantLib"],
            resources: [.copy("Fixtures")]
        )
    ]
)
