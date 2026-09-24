import Foundation

/// UserDefaults keys, shared by @AppStorage in views and by background code.
enum SettingsKey {
    static let saved = "savedAirports"
    static let home = "homeAirport"
    static let notifyEnabled = "notifyEnabled"
    static let notifyMode = "notifyMode"            // NotifyMode raw value
    static let lastNotifiedCycle = "lastNotifiedCycle"
    static let historyRange = "historyRange"        // HistoryRange raw value
    static let historyShowFYI = "historyShowFYI"
    static let onboarded = "hasOnboarded"
}

enum NotifyMode: String, CaseIterable, Identifiable {
    case action, any
    var id: String { rawValue }
    var title: String {
        switch self {
        case .action: "Action items only"
        case .any: "Any change"
        }
    }
}

enum HistoryRange: String, CaseIterable, Identifiable {
    case threeMonths = "3M", sixMonths = "6M", year = "1Y", all = "ALL"
    var id: String { rawValue }
    var months: Int? {
        switch self {
        case .threeMonths: 3
        case .sixMonths: 6
        case .year: 12
        case .all: nil
        }
    }
}
