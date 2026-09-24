import Foundation

// Mirrors SCHEMA.md (schema_version 1). Decoded with .convertFromSnakeCase.

struct Meta: Decodable, Sendable {
    let schemaVersion: Int
    let fromCycle: String
    let toCycle: String
    let upcoming: Bool
    let includesCharts: Bool
    let changedAirports: Int
    let generated: String
}

struct Counts: Decodable, Sendable, Hashable {
    let action: Int
    let ifr: Int
    let fyi: Int
    var total: Int { action + ifr + fyi }
}

struct LatestIndex: Decodable, Sendable {
    let schemaVersion: Int
    let fromCycle: String
    let toCycle: String
    let airports: [String: Counts]
}

struct AirportChanges: Decodable, Sendable {
    let schemaVersion: Int
    let airport: String
    let fromCycle: String
    let toCycle: String
    let counts: Counts
    let changes: [Change]
}

struct AirportHistory: Decodable, Sendable {
    let schemaVersion: Int
    let airport: String
    let firstCycle: String
    let lastCycle: String
    let entries: [Change]
}

struct AirportDirectory: Decodable, Sendable {
    let schemaVersion: Int
    let cycle: String
    let airports: [AirportInfo]
}

struct AirportInfo: Decodable, Sendable, Identifiable, Hashable {
    let id: String
    let icao: String?
    let name: String
    let city: String?
    let state: String?
    let type: String?
    let lat: Double?
    let lon: Double?

    /// "Daytona Beach, FL"
    var location: String {
        [city, state].compactMap { $0 }.joined(separator: ", ")
    }
}

/// One change. History entries are the same shape plus `cycle` / `fromCycle`.
struct Change: Decodable, Identifiable, Hashable, Sendable {
    let id: String
    let priority: String
    let category: String
    let kind: String
    let summary: String
    let source: String
    let original: String?
    let fields: [FieldChange]?
    let details: [String]?
    let procedures: Procedures?
    let chart: Chart?
    let cycle: String?        // history only
    let fromCycle: String?    // history only

    var level: Priority { Priority(rawValue: priority) ?? .fyi }
}

struct FieldChange: Decodable, Sendable, Hashable {
    let field: String
    let old: String
    let new: String
}

struct Procedures: Decodable, Sendable, Hashable {
    let updated: [String]
    let removed: [String]
}

struct Chart: Decodable, Sendable, Hashable {
    let code: String
    let name: String
    let amdt: String?
    let pdf: String?

    /// "AMDT 11C" / "ORIG" / nil
    var amdtLabel: String? {
        guard let amdt, !amdt.isEmpty else { return nil }
        return ["0", "ORIG"].contains(amdt.uppercased()) ? "ORIG" : "AMDT \(amdt)"
    }
}

enum Priority: String, CaseIterable, Identifiable, Sendable {
    case action, ifr, fyi
    var id: String { rawValue }

    var title: String {
        switch self {
        case .action: "Action"
        case .ifr: "IFR Procedures"
        case .fyi: "FYI"
        }
    }
}

/// FAA cycle dates ("2026-10-01"). Everything in UTC so a cycle never shows as the day before.
enum Cycle {
    private static let utc = TimeZone(identifier: "UTC")!

    private static let parser: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = utc
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()

    private static let efbFormatter: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = utc
        f.dateFormat = "dd MMM yyyy"
        return f
    }()

    static func date(_ cycle: String) -> Date? { parser.date(from: cycle) }

    static func string(_ date: Date) -> String { parser.string(from: date) }

    /// "01 OCT 2026"
    static func efb(_ cycle: String) -> String {
        guard let d = date(cycle) else { return cycle }
        return efbFormatter.string(from: d).uppercased()
    }

    /// "03 SEP"
    static func efbShort(_ cycle: String) -> String {
        String(efb(cycle).prefix(6))
    }

    /// "2026-10-01" shifted by n days (a cycle is valid until the day before the next one)
    static func shift(_ cycle: String, days: Int) -> String {
        guard let d = date(cycle) else { return cycle }
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = utc
        return cal.date(byAdding: .day, value: days, to: d).map { string($0) } ?? cycle
    }

    /// days from today until the cycle takes effect (negative = already effective)
    static func daysUntil(_ cycle: String) -> Int? {
        guard let d = date(cycle) else { return nil }
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = utc
        let today = cal.startOfDay(for: .now)
        return cal.dateComponents([.day], from: today, to: d).day
    }
}
