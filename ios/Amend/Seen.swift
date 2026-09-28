import Foundation

/// what you'd already seen at an airport the last time you looked
struct SeenRecord: Codable, Sendable {
    let cycle: String
    let at: Date
    let ids: [String]
}

/// the "New" labels, the same rule as amend.watch: a change is new if it's from the cycle you last looked at (or
/// later) and wasn't there when you looked. The first look at an airport marks nothing, so a fresh install isn't a
/// wall of "New".
extension AirportStore {
    /// the ids that are new since the last look (empty on a first look)
    func newIDs(_ airport: String, _ changes: [Change], cycle: String) -> Set<String> {
        guard let prev = seen[airport], cycle >= prev.cycle else { return [] }
        let had = Set(prev.ids)
        return Set(changes.map(\.id).filter { !had.contains($0) })
    }

    /// how many of an airport's loaded changes are new, for the counts on home
    func newCount(_ airport: String) -> Int {
        guard let data = latest[airport] else { return 0 }
        return newIDs(airport, data.changes, cycle: data.toCycle).count
    }

    /// you just looked at this airport's changes
    func look(_ airport: String, _ changes: [Change], cycle: String) {
        seen[airport] = SeenRecord(cycle: cycle, at: .now, ids: Array(changes.map(\.id).prefix(400)))
        saveSeen()
    }

    /// seen on home without being opened: remember what's there the first time, so what comes later counts as new
    func baseline(_ airport: String, _ changes: [Change], cycle: String) {
        guard seen[airport] == nil else { return }
        seen[airport] = SeenRecord(cycle: cycle, at: .now, ids: changes.map(\.id))
        saveSeen()
    }

    nonisolated static func loadSeen() -> [String: SeenRecord] {
        UserDefaults.standard.data(forKey: SettingsKey.seen)
            .flatMap { try? JSONDecoder().decode([String: SeenRecord].self, from: $0) } ?? [:]
    }

    private func saveSeen() {
        if let d = try? JSONEncoder().encode(seen) { UserDefaults.standard.set(d, forKey: SettingsKey.seen) }
    }
}
