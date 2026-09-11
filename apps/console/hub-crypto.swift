import Foundation
import CryptoKit

// Native authenticated encryption for the owner's recovery capsule. Keys never go on stdout.
let args = Array(CommandLine.arguments.dropFirst())
guard args.count == 4, ["seal", "open"].contains(args[0]) else {
    fputs("Usage: hub-crypto seal|open key-file input output\n", stderr); exit(64)
}
do {
    let keyData = try Data(contentsOf: URL(fileURLWithPath: args[1]))
    guard keyData.count == 32 else { throw NSError(domain: "recovery", code: 1) }
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
