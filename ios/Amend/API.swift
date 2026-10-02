import Foundation

enum APIError: LocalizedError {
    case badStatus(Int)
    case missing(String)
    var errorDescription: String? {
        switch self {
        case .badStatus(let code): "Server returned \(code)"
        case .missing(let id): "Amend's data for \(id) is missing or still updating. Try again in a few minutes."
        }
    }
}

struct API {
    static let base = URL(string: "https://amend.watch/")!

    static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    /// raw bytes, or nil on 404 (Amend only publishes files for airports that changed)
    static func data(_ path: String) async throws -> Data? {
        let sent = Date.now
        let (data, response) = try await URLSession.shared.data(from: base.appending(path: path))
        if let http = response as? HTTPURLResponse {
            ServerClock.update(http, sent: sent)
            if http.statusCode == 404 { return nil }
            guard (200..<300).contains(http.statusCode) else { throw APIError.badStatus(http.statusCode) }
        }
        return data
    }

    private static func get<T: Decodable>(_ path: String) async throws -> T? {
        guard let data = try await data(path) else { return nil }
        return try decoder.decode(T.self, from: data)
    }

    static func meta() async throws -> Meta? { try await get("latest/meta.json") }
    static func latestIndex() async throws -> LatestIndex? { try await get("latest/index.json") }
    static func latest(_ id: String) async throws -> AirportChanges? { try await get("latest/\(id).json") }
    static func history(_ id: String) async throws -> AirportHistory? { try await get("history/\(id).json") }
}

/// the FAA's own publications, for checking a change against the source (the same links as amend.watch)
enum FAALinks {
    static let supplement = URL(string: "https://www.faa.gov/air_traffic/flight_info/aeronav/digital_products/dafd/search/")!
    static let dtpp = URL(string: "https://www.faa.gov/air_traffic/flight_info/aeronav/digital_products/dtpp/search/")!
    static let notams = URL(string: "https://notams.aim.faa.gov/notamSearch/")!

    /// the NASR subscription page for one cycle ("2026-10-01")
    static func nasr(_ cycle: String) -> URL? {
        URL(string: "https://www.faa.gov/air_traffic/flight_info/aeronav/aero_data/NASR_Subscription/\(cycle)")
    }

    /// where a change came from: the chart search for charts, the NASR cycle page for everything else
    static func source(for change: Change, cycle: String?) -> URL? {
        if change.source.uppercased() == "D-TPP" || change.chart != nil { return dtpp }
        return (change.cycle ?? cycle).flatMap { nasr($0) }
    }

    static let reportEmail = "hello@amend.watch"

    /// an email to reportEmail with the subject and a short form filled in, like the website's report links.
    /// no airport: the general "Report a problem"
    static func report(_ id: String? = nil, cycle: String? = nil) -> URL? {
        var c = URLComponents()
        c.scheme = "mailto"
        c.path = reportEmail
        let lines = [id.map { "Airport: \($0)" }, cycle.map { "Cycle: \(Cycle.efb($0))" },
                     id.map { "Page: https://amend.watch/\($0)/" }].compactMap { $0 }
        let form = "What looks wrong:\n\n\nWhat the FAA source says (a link or screenshot helps):\n"
        c.queryItems = [
            URLQueryItem(name: "subject", value: id.map { "Amend: wrong change at \($0)" } ?? "Amend: a problem"),
            URLQueryItem(name: "body", value: lines.isEmpty ? form : lines.joined(separator: "\n") + "\n\n" + form),
        ]
        return c.url
    }
}
