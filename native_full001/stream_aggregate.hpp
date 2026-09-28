#pragma once
#include "common.hpp"
#include <mutex>
namespace full {
// Retains one accumulator per group/aggregate. No input Table, row index,
// RecordBatch or pointer into an input buffer survives consume().
class StreamAggregate {
    struct Acc { J value=nullptr; int64_t count=0; };
    struct Group { J::A keys; std::vector<Acc> aggregates; };
    std::shared_ptr<arrow::Schema> schema_;
    J params_;
    std::vector<int> columns_;
    std::vector<int> inputs_;
    std::unordered_map<std::string,Group> groups_;
    Counts counts_;
    bool closed_=false,failed_=false;
    std::mutex mutex_;
    void live(){if(closed_||failed_)throw Fault("AGGREGATE_STATE_CLOSED");}
public:
    StreamAggregate(Table empty,J params):schema_(empty->schema()),params_(std::move(params)) {
        columns_=columns(empty,params_.at("group_by"));
        for(auto&s:params_.at("aggregates").arr()) {
            auto fn=s.at("function").str();
            if(fn!="count"&&fn!="sum"&&fn!="mean"&&fn!="min"&&fn!="max")throw Fault("AGGREGATE_FUNCTION","plan");
            int input=s.at("field").null()?-1:schema_->GetFieldIndex(s.at("field").str());
            if(input<0&&(fn!="count"||!s.at("field").null()))throw Fault("FIELD_NOT_FOUND","plan");
            inputs_.push_back(input);
        }
        if(columns_.empty())groups_["[]"]={J::A{},std::vector<Acc>(inputs_.size())};
    }
    void consume(Table batch) {
        std::lock_guard<std::mutex> lock(mutex_);live();
        try {
            if(batch->num_columns()!=schema_->num_fields())throw Fault("AGGREGATE_BATCH_SCHEMA");
            for(int col=0;col<batch->num_columns();++col)
                if(batch->field(col)->name()!=schema_->field(col)->name()||!batch->field(col)->type()->Equals(schema_->field(col)->type()))throw Fault("AGGREGATE_BATCH_SCHEMA");
            for(int64_t row=0;row<batch->num_rows();++row) {
                auto k=key(batch,row,columns_);auto found=groups_.find(k);
                if(found==groups_.end()) {
                    J::A keys;for(int col:columns_)keys.push_back(cell(batch,col,row));
                    found=groups_.emplace(k,Group{std::move(keys),std::vector<Acc>(inputs_.size())}).first;
                }
                count(counts_,"hash_probes");
                for(size_t a=0;a<inputs_.size();++a) {
                    auto value=inputs_[a]<0?J(1):cell(batch,inputs_[a],row);if(value.null())continue;
                    auto&acc=found->second.aggregates[a];
                    if(acc.count==INT64_MAX)throw Fault("ARITHMETIC_OVERFLOW","plan");
                    ++acc.count;count(counts_,"values_accumulated");auto fn=params_.at("aggregates").arr()[a].at("function").str();
                    if(fn=="count")continue;
                    if(acc.value.null())acc.value=fn=="mean"?J(value.d()):value;
                    else if(fn=="sum"||fn=="mean")acc.value=arithmetic("add",acc.value,value);
                    else if((fn=="min"&&compare(value,acc.value)<0)||(fn=="max"&&compare(value,acc.value)>0))acc.value=value;
                }
            }
            count(counts_,"rows_in",batch->num_rows());count(counts_,"input_batches");
            if constexpr(RCWG_FULL_DIAGNOSTICS) {
                counts_["peak_input_batch_rows"]=std::max(counts_["peak_input_batch_rows"],batch->num_rows());
                counts_["peak_group_states"]=std::max(counts_["peak_group_states"],int64_t(groups_.size()));
                counts_["retained_input_rows"]=0;
            }
        }catch(...){failed_=true;throw;}
    }
    std::pair<Table,Counts> finish() {
        std::lock_guard<std::mutex> lock(mutex_);live();closed_=true;
        std::vector<std::shared_ptr<arrow::Field>> fields;for(int col:columns_)fields.push_back(schema_->field(col));
        for(size_t a=0;a<inputs_.size();++a) {
            auto&s=params_.at("aggregates").arr()[a];auto fn=s.at("function").str();
            auto type=fn=="count"?arrow::int64():fn=="mean"?arrow::float64():schema_->field(inputs_[a])->type();
            fields.push_back(arrow::field(s.at("as").str(),type,fn!="count"));
        }
        J::A rows;
        std::vector<std::string> keys;for(auto&[key,_]:groups_)keys.push_back(key);std::sort(keys.begin(),keys.end());
        for(auto&key:keys) {
            auto&group=groups_.at(key);
            J::O row;for(size_t k=0;k<columns_.size();++k)row[schema_->field(columns_[k])->name()]=group.keys[k];
            for(size_t a=0;a<inputs_.size();++a) {
                auto&s=params_.at("aggregates").arr()[a];auto fn=s.at("function").str();auto&acc=group.aggregates[a];
                row[s.at("as").str()]=fn=="count"?J(acc.count):fn=="mean"&&acc.count?J(acc.value.d()/double(acc.count)):acc.value;
            }
            rows.push_back(std::move(row));
        }
        count(counts_,"groups",groups_.size());auto result=from_rows(rows,arrow::schema(fields));groups_.clear();return {result,counts_};
    }
};
}
