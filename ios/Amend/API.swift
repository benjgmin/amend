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
    static let base = URL(string: "https://benjgmin.github.io/amend/")!

    static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    /// raw bytes, or nil on 404 (Amend only publishes files for airports that changed)
    static func data(_ path: String) async throws -> Data? {
        let (data, response) = try await URLSession.shared.data(from: base.appending(path: path))
        if let http = response as? HTTPURLResponse {
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
