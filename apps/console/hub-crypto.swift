import Foundation
import CryptoKit
import Darwin

// Native authenticated encryption for the owner's recovery capsule. Keys never go on stdout.
let args = Array(CommandLine.arguments.dropFirst())
guard args.count == 4, ["seal", "open", "seal-stream", "open-stream"].contains(args[0]) else {
    fputs("Usage: hub-crypto seal|open key-file input output\n", stderr); exit(64)
}
do {
    let keyData = try Data(contentsOf: URL(fileURLWithPath: args[1]))
    guard keyData.count == 32 else { throw NSError(domain: "recovery", code: 1) }
    if args[0].hasSuffix("-stream") {
        try stream(args[0], key: SymmetricKey(data: keyData), input: args[2], output: args[3])
        exit(0)
    }
    let inputURL = URL(fileURLWithPath: args[2])
    let size = try inputURL.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? Int.max
    guard size <= 536870912 else { throw NSError(domain: "recovery", code: 2) }
    let input = try Data(contentsOf: inputURL)
    let key = SymmetricKey(data: keyData)
    let output: Data
    if args[0] == "seal" {
        output = try AES.GCM.seal(input, using: key).combined!
    } else {
        output = try AES.GCM.open(AES.GCM.SealedBox(combined: input), using: key)
    }
    try output.write(to: URL(fileURLWithPath: args[3]), options: .withoutOverwriting)
    try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: args[3])
} catch {
    fputs("Recovery encryption failed: check the key, capsule integrity and destination.\n", stderr); exit(65)
}

// Version 2 is bounded-memory AES-GCM framing. Every frame authenticates the
// random stream identity and sequence number; an authenticated empty frame ends
// the stream. Missing, reordered, substituted and trailing frames are rejected.
func stream(_ mode: String, key: SymmetricKey, input: String, output: String) throws {
    let chunk = 4 * 1024 * 1024
    let magic = Data("SOVBKP02".utf8)
    let src = try FileHandle(forReadingFrom: URL(fileURLWithPath: input))
    defer { try? src.close() }
    let fd = Darwin.open(output, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0o600)
    guard fd >= 0 else { throw NSError(domain: "backup-output", code: 1) }
    let dst = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
    var complete = false
    defer { try? dst.close(); if !complete { try? FileManager.default.removeItem(atPath: output) } }
    func fail() -> NSError { NSError(domain: "backup-stream", code: 1) }
    func exact(_ n: Int) throws -> Data {
        var bytes = Data()
        while bytes.count < n {
            guard let part = try src.read(upToCount: n - bytes.count), !part.isEmpty else { throw fail() }
            bytes.append(part)
        }
        return bytes
    }
    func countBytes(_ value: UInt64) -> Data {
        var big = value.bigEndian
        return withUnsafeBytes(of: &big) { Data($0) }
    }
    let header: Data
    if mode == "seal-stream" {
        header = magic + SymmetricKey(size: .bits128).withUnsafeBytes { Data($0) }
        try dst.write(contentsOf: header)
    } else {
        header = try exact(24)
        guard header.prefix(8) == magic else { throw fail() }
    }
    var index: UInt64 = 0
    while true {
        let aad = header + countBytes(index)
        if mode == "seal-stream" {
            let plain = try src.read(upToCount: chunk) ?? Data()
            let sealed = try AES.GCM.seal(plain, using: key, authenticating: aad).combined!
            try dst.write(contentsOf: countBytes(UInt64(sealed.count)))
            try dst.write(contentsOf: sealed)
            if plain.isEmpty { break }
        } else {
            let length = try exact(8).reduce(UInt64(0)) { ($0 << 8) | UInt64($1) }
            guard length >= 28, length <= UInt64(chunk + 28) else { throw fail() }
            let plain = try AES.GCM.open(AES.GCM.SealedBox(combined: exact(Int(length))), using: key, authenticating: aad)
            if plain.isEmpty {
                guard (try src.read(upToCount: 1) ?? Data()).isEmpty else { throw fail() }
                break
            }
            try dst.write(contentsOf: plain)
        }
        index += 1
        guard index <= 262144 else { throw fail() } // 1 TiB maximum stream
    }
    try dst.synchronize()
    complete = true
}
