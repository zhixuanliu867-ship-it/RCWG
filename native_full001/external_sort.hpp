#pragma once
#include "common.hpp"
namespace full {
// The old Table -> spill -> materialized Table facade is unavailable.
// Use StreamSort.consume()/finish() and read the resulting Arrow stream.
// Native.relational preserves Python convenience calls with a lazy disk handle.
inline Table external_sort(Table,const J&,const std::string&,Counts&){
    throw Fault("BOUNDED_STREAM_ENTRYPOINT_REQUIRED","facility");
}
}
