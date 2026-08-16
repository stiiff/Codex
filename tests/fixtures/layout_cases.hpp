#include <cstdint>

struct Narrow {
    uint7 head;
    uint7 value;
};

struct Wide {
    uint7 head;
    uint12 value;
};

struct ExactByte {
    uint3 prefix;
    uint8 byte;
};

struct WordReorder {
    uint17 a;
    uint8 b;
    uint15 c;
};

struct ReservedSplit {
    uint17 a;
    uint12 b;
    uint7 spare_rsvd;
};

struct NestedChild {
    uint17 wide;
    uint8 small;
};

struct NestedParent {
    uint7 head;
    NestedChild child;
    uint8 parent_rsvd;
};

struct ArrayElement {
    uint9 a;
    uint7 b;
};

struct ArrayCase {
    ArrayElement items[3];
};

union TestUnion {
    uint12 a;
    uint17 b;
};

struct ReservedChild {
    uint5 x;
    uint3 child_rsvd;
};

struct ReservedParent {
    ReservedChild child;
    uint8 y;
};

struct Comparison {
    uint17 a;
    uint12 b;
    uint3 comparison_rsvd;
};

struct Coordinate {
    uint17 x;
    uint15 y;
};

union SensorValue {
    uint31 raw;
    uint32_t signed_magnitude : 29;
    Coordinate coordinate;
};

struct Record {
    SensorValue sensor;
    uint7 channel;
    uint12 samples[4];
    uint1 record_rsvd;
};

struct TelemetryPacket {
    uint5 packet_type;
    uint19 sequence;
    Record records[16];
    uint1 packet_rsvd;
};
