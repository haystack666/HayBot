// Read-only verification of the test-owned Chrome process; never changes activation policy.
import AppKit
import CoreGraphics
import Foundation

let pid = pid_t(CommandLine.arguments[1])!
let app = NSRunningApplication(processIdentifier: pid)
let windows = CGWindowListCopyWindowInfo([.optionAll, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] ?? []
let owned = windows.filter { ($0[kCGWindowOwnerPID as String] as? Int) == Int(pid) }
let result: [String: Any] = [
    "pid": Int(pid),
    "registered": app != nil,
    "activationPolicy": app.map { $0.activationPolicy.rawValue } ?? -1,
    "active": app?.isActive ?? false,
    "windowCount": owned.count,
    "visibleWindowCount": owned.filter { ($0[kCGWindowIsOnscreen as String] as? Bool) == true }.count
]
let data = try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
print(String(data: data, encoding: .utf8)!)
