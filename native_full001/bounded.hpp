#pragma once
#include "common.hpp"
#include <arrow/io/api.h>
#include <arrow/ipc/api.h>
#include <mutex>
#include <set>

namespace full {
inline bool batch_schema(const Table&t,const std::shared_ptr<arrow::Schema>&schema){
    if(t->num_columns()!=schema->num_fields())return false;
    for(int i=0;i<t->num_columns();++i)if(t->field(i)->name()!=schema->field(i)->name()||!t->field(i)->type()->Equals(schema->field(i)->type()))return false;
    return true;
}
inline bool row_before(const J&a,int64_t ai,const J&b,int64_t bi,const J&keys,Counts&c){
    count(c,"key_comparisons");
    for(auto&k:keys.arr()){
        auto&x=a.at(k.at("field").str());auto&y=b.at(k.at("field").str());
        if(x.null()||y.null()){
            if(x.null()&&y.null())continue;
            bool first=k.has("nulls")&&k.at("nulls").str()=="first";
            return x.null()?first:!first;
        }
        int cmp=compare(x,y);if(cmp)return k.at("direction").str()=="asc"?cmp<0:cmp>0;
    }
    return ai<bi;
}

class StreamTopK {
    struct Entry{J value;int64_t ordinal;};
    std::shared_ptr<arrow::Schema> schema_;
    J params_;int64_t k_,ordinal_=0,retained_=0;bool closed_=false;
    std::vector<int> groupcols_;std::map<std::string,std::vector<Entry>> groups_;
    Counts counts_;std::mutex mutex_;
public:
    StreamTopK(Table empty,J params):schema_(empty->schema()),params_(std::move(params)),k_(params_.at("k").i()){
        if(k_<0)throw Fault("PARAMETER_RANGE","plan");
        if(params_.has("partition_by"))groupcols_=columns(empty,params_.at("partition_by"));
    }
    void consume(Table batch){
        std::lock_guard<std::mutex> lock(mutex_);
        if(closed_)throw Fault("TOPK_STATE_CLOSED");
        if(!batch_schema(batch,schema_))throw Fault("TOPK_BATCH_SCHEMA");
        auto less=[&](const Entry&a,const Entry&b){return row_before(a.value,a.ordinal,b.value,b.ordinal,params_.at("keys"),counts_);};
        for(int64_t i=0;i<batch->num_rows();++i){
            if(ordinal_==INT64_MAX)throw Fault("ROW_ORDINAL_OVERFLOW","plan");
            auto ordinal=ordinal_++;count(counts_,"rows_in");if(!k_)continue;
            auto&heap=groups_[key(batch,i,groupcols_)];Entry entry{row(batch,i),ordinal};
            if(int64_t(heap.size())<k_){heap.push_back(std::move(entry));std::push_heap(heap.begin(),heap.end(),less);++retained_;count(counts_,"heap_pushes");}
            else if(less(entry,heap.front())){
                std::pop_heap(heap.begin(),heap.end(),less);heap.back()=std::move(entry);std::push_heap(heap.begin(),heap.end(),less);count(counts_,"heap_replacements");
            }
        }
        count(counts_,"input_batches");
        if constexpr(RCWG_FULL_DIAGNOSTICS){
            counts_["peak_retained_rows"]=std::max(counts_["peak_retained_rows"],retained_);
            counts_["peak_input_batch_rows"]=std::max(counts_["peak_input_batch_rows"],batch->num_rows());
            counts_["retained_input_buffers"]=0;
        }
    }
    std::pair<Table,Counts> finish(){
        std::lock_guard<std::mutex> lock(mutex_);if(closed_)throw Fault("TOPK_STATE_CLOSED");closed_=true;
        auto less=[&](const Entry&a,const Entry&b){return row_before(a.value,a.ordinal,b.value,b.ordinal,params_.at("keys"),counts_);};
        J::A rows;for(auto&[_,heap]:groups_){std::sort(heap.begin(),heap.end(),less);for(auto&v:heap)rows.push_back(std::move(v.value));}
        groups_.clear();return {from_rows(rows,schema_),counts_};
    }
};

struct SpillCursor {
    std::shared_ptr<arrow::io::ReadableFile> file;
    std::shared_ptr<arrow::RecordBatchReader> reader;
    Table table;int64_t index=0;
    explicit SpillCursor(const std::string&path){file=take(arrow::io::ReadableFile::Open(path));reader=take(arrow::ipc::RecordBatchStreamReader::Open(file));next_batch();}
    void next_batch(){
        do{auto b=take(reader->Next());table=b?take(arrow::Table::FromRecordBatches({b})):nullptr;index=0;}
        while(table&&table->num_rows()==0);
    }
    void advance(){if(++index==table->num_rows())next_batch();}
    J value()const{return row(table,index);}
};

class SpillWriter {
    std::shared_ptr<arrow::io::FileOutputStream> file_;
    std::shared_ptr<arrow::ipc::RecordBatchWriter> writer_;
    std::shared_ptr<arrow::Schema> schema_;J::A rows_;size_t bytes_=0;
public:
    int64_t rows=0;
    SpillWriter(const std::string&path,std::shared_ptr<arrow::Schema> schema):schema_(std::move(schema)){
        if(std::filesystem::exists(path))throw Fault("EXCLUSIVE_PATH_REQUIRED");
        file_=take(arrow::io::FileOutputStream::Open(path));writer_=take(arrow::ipc::MakeStreamWriter(file_,schema_));
    }
    void append(J value){
        auto size=dump(value).size();
        if(size>64*1024*1024)throw Fault("DECLARED_OBJECT_LIMIT_EXCEEDED","plan");
        if(!rows_.empty()&&(rows_.size()>=1024||bytes_+size>4*1024*1024))flush();
        rows_.push_back(std::move(value));bytes_+=size;++rows;
    }
    void append_table(Table table){flush();ok(writer_->WriteTable(*table,1024));rows+=table->num_rows();}
    void flush(){if(rows_.empty())return;auto table=from_rows(rows_,schema_);ok(writer_->WriteTable(*table,1024));rows_.clear();bytes_=0;}
    void finish(){flush();ok(writer_->Close());ok(file_->Close());}
};

class StreamSort {
    std::shared_ptr<arrow::Schema> schema_,spill_schema_;J params_;std::string directory_,ordinal_name_;
    int64_t ordinal_=0,path_id_=0;bool closed_=false;
    std::vector<std::vector<std::string>> levels_;std::set<std::string> owned_;Counts counts_;std::mutex mutex_;
    std::string path(){auto p=(std::filesystem::path(directory_)/("run-"+std::to_string(path_id_++)+".arrowstream")).string();
        if(std::filesystem::exists(p))throw Fault("EXCLUSIVE_PATH_REQUIRED");owned_.insert(p);return p;}
    void remove(const std::string&p){std::filesystem::remove(p);owned_.erase(p);}
    std::string merge(const std::vector<std::string>&runs){
        std::vector<SpillCursor> cursors;for(auto&p:runs){cursors.emplace_back(p);count(counts_,"spill_read_bytes",std::filesystem::file_size(p));}
        auto later=[&](size_t a,size_t b){auto x=cursors[a].value(),y=cursors[b].value();
            return row_before(y,y.at(ordinal_name_).i(),x,x.at(ordinal_name_).i(),params_.at("keys"),counts_);};
        std::priority_queue<size_t,std::vector<size_t>,decltype(later)> heap(later);
        for(size_t i=0;i<cursors.size();++i)if(cursors[i].table)heap.push(i);
        auto output=path();SpillWriter writer(output,spill_schema_);
        while(!heap.empty()){auto i=heap.top();heap.pop();writer.append(cursors[i].value());cursors[i].advance();if(cursors[i].table)heap.push(i);}
        writer.finish();cursors.clear();for(auto&p:runs)remove(p);
        count(counts_,"merge_passes");count(counts_,"spill_write_bytes",std::filesystem::file_size(output));
        if constexpr(RCWG_FULL_DIAGNOSTICS)counts_["peak_merge_readers"]=std::max(counts_["peak_merge_readers"],int64_t(runs.size()));
        return output;
    }
    void insert(std::string run,size_t level=0){
        if(level==levels_.size())levels_.emplace_back();levels_[level].push_back(run);
        if(levels_[level].size()==8){auto combined=merge(levels_[level]);levels_[level].clear();insert(combined,level+1);}
    }
public:
    StreamSort(Table empty,J params,const std::string&directory):schema_(empty->schema()),params_(std::move(params)),directory_(directory){
        if(directory.empty()||!std::filesystem::is_directory(directory)||std::filesystem::is_symlink(directory))throw Fault("SPILL_DIRECTORY_INVALID");
        ordinal_name_="__full001_ordinal";while(schema_->GetFieldIndex(ordinal_name_)>=0)ordinal_name_+="_";
        spill_schema_=take(schema_->AddField(schema_->num_fields(),arrow::field(ordinal_name_,arrow::int64(),false)));
    }
    ~StreamSort(){for(auto&p:owned_){std::error_code error;std::filesystem::remove(p,error);}}
    int64_t rows()const{return ordinal_;}
    void consume(Table batch){
        std::lock_guard<std::mutex> lock(mutex_);if(closed_)throw Fault("SORT_STATE_CLOSED");
        if(!batch_schema(batch,schema_))throw Fault("SORT_BATCH_SCHEMA");
        for(int64_t base=0;base<batch->num_rows();base+=1024){
            auto block=batch->Slice(base,std::min<int64_t>(1024,batch->num_rows()-base));auto order=ordinals(block->num_rows());
            std::sort(order.begin(),order.end(),Order{block,params_.at("keys"),&counts_});auto sorted=select(block,order);
            if(ordinal_>INT64_MAX-block->num_rows())throw Fault("ROW_ORDINAL_OVERFLOW","plan");
            arrow::Int64Builder ord;for(auto i:order)ok(ord.Append(ordinal_+i));ordinal_+=block->num_rows();
            sorted=take(sorted->AddColumn(sorted->num_columns(),spill_schema_->field(spill_schema_->num_fields()-1),std::make_shared<arrow::ChunkedArray>(take(ord.Finish()))));
            auto output=path();SpillWriter writer(output,spill_schema_);writer.append_table(sorted);writer.finish();insert(output);
            count(counts_,"sort_runs");count(counts_,"rows_in",block->num_rows());
            if constexpr(RCWG_FULL_DIAGNOSTICS)counts_["peak_sort_run_rows"]=std::max(counts_["peak_sort_run_rows"],block->num_rows());
        }
        count(counts_,"input_batches");
    }
    std::pair<std::string,Counts> finish(){
        std::lock_guard<std::mutex> lock(mutex_);if(closed_)throw Fault("SORT_STATE_CLOSED");closed_=true;
        std::vector<std::string> remaining;for(auto&level:levels_)for(auto&p:level)remaining.push_back(p);
        while(remaining.size()>1){std::vector<std::string> next;for(size_t i=0;i<remaining.size();i+=8){
            std::vector<std::string> part(remaining.begin()+i,remaining.begin()+std::min(i+8,remaining.size()));next.push_back(merge(part));}remaining=std::move(next);}
        auto output=path();SpillWriter writer(output,schema_);
        if(!remaining.empty()){
            {SpillCursor cursor(remaining[0]);while(cursor.table){auto value=cursor.value();std::get<J::O>(value.v).erase(ordinal_name_);writer.append(std::move(value));cursor.advance();}}
            remove(remaining[0]);
        }
        writer.finish();owned_.erase(output);count(counts_,"rows_out",writer.rows);
        count(counts_,"spill_write_bytes",std::filesystem::file_size(output));
        return {output,counts_};
    }
};
}
