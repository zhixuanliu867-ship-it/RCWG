#pragma once
#include "common.hpp"
#include <arrow/io/api.h>
#include <arrow/ipc/api.h>
namespace full {
// Each spill contains the complete Arrow payload and a stable source ordinal.
// Merge readers retain one bounded batch apiece; at most eight readers per pass.
inline Table external_sort(Table input,const J&params,const std::string& directory,Counts&c){
    if(directory.empty()||!std::filesystem::is_directory(directory)||std::filesystem::is_symlink(directory))throw Fault("SPILL_DIRECTORY_INVALID");
    std::vector<std::filesystem::path> all;
    struct Cleanup{std::vector<std::filesystem::path>&all;~Cleanup(){for(auto&p:all){std::error_code ec;std::filesystem::remove(p,ec);}}} cleanup{all};
    auto new_path=[&](){auto p=std::filesystem::path(directory)/("full001-sort-"+std::to_string(all.size())+".arrow");
        if(std::filesystem::exists(p))throw Fault("EXCLUSIVE_PATH_REQUIRED");all.push_back(p);return p;};
    std::string ordinal="__full001_ordinal";while(input->schema()->GetFieldIndex(ordinal)>=0)ordinal+="_";
    auto schema=take(input->schema()->AddField(input->num_columns(),arrow::field(ordinal,arrow::int64(),false)));
    auto save=[&](const std::filesystem::path& path,Table table){
        auto file=take(arrow::io::FileOutputStream::Open(path.string()));auto writer=take(arrow::ipc::MakeStreamWriter(file,schema));
        ok(writer->WriteTable(*table,1024));ok(writer->Close());ok(file->Close());count(c,"spill_write_bytes",std::filesystem::file_size(path));};
    std::vector<std::filesystem::path> runs;
    for(int64_t base=0;base<input->num_rows();base+=1024){
        auto block=input->Slice(base,std::min<int64_t>(1024,input->num_rows()-base));auto order=ordinals(block->num_rows());
        std::sort(order.begin(),order.end(),Order{block,params.at("keys"),&c});auto sorted=select(block,order);
        arrow::Int64Builder ord;for(auto i:order)ok(ord.Append(base+i));
        sorted=take(sorted->AddColumn(sorted->num_columns(),schema->field(schema->num_fields()-1),std::make_shared<arrow::ChunkedArray>(take(ord.Finish()))));
        auto path=new_path();save(path,sorted);runs.push_back(path);count(c,"sort_runs");
    }
    if(runs.empty())return input->Slice(0,0);
    struct Cursor{
        std::shared_ptr<arrow::io::ReadableFile> file;std::shared_ptr<arrow::RecordBatchReader> reader;Table table;int64_t row=0;
        explicit Cursor(const std::filesystem::path&p){file=take(arrow::io::ReadableFile::Open(p.string()));reader=take(arrow::ipc::RecordBatchStreamReader::Open(file));next_batch();}
        void next_batch(){auto b=take(reader->Next());table=b?take(arrow::Table::FromRecordBatches({b})):nullptr;row=0;}
        void advance(){if(++row==table->num_rows())next_batch();}
    };
    while(runs.size()>1){
        std::vector<std::filesystem::path> merged;count(c,"merge_passes");
        for(size_t base=0;base<runs.size();base+=8){
            std::vector<Cursor> cursors;for(size_t i=base;i<std::min(base+8,runs.size());++i){cursors.emplace_back(runs[i]);count(c,"spill_read_bytes",std::filesystem::file_size(runs[i]));}
            auto later=[&](size_t ai,size_t bi){auto&a=cursors[ai];auto&b=cursors[bi];count(c,"key_comparisons");
                for(auto&k:params.at("keys").arr()){auto x=field(a.table,a.row,k.at("field").str()),y=field(b.table,b.row,k.at("field").str());
                    if(x.null()||y.null()){if(x.null()&&y.null())continue;bool first=k.has("nulls")&&k.at("nulls").str()=="first";return x.null()?!first:first;}
                    int cmp=compare(x,y);if(cmp)return k.at("direction").str()=="asc"?cmp>0:cmp<0;
                }return field(a.table,a.row,ordinal).i()>field(b.table,b.row,ordinal).i();};
            std::priority_queue<size_t,std::vector<size_t>,decltype(later)> queue(later);
            for(size_t i=0;i<cursors.size();++i)if(cursors[i].table)queue.push(i);
            auto path=new_path();auto file=take(arrow::io::FileOutputStream::Open(path.string()));auto writer=take(arrow::ipc::MakeStreamWriter(file,schema));J::A buffer;size_t bytes=0;
            auto flush=[&](){if(buffer.empty())return;auto table=from_rows(buffer,schema);ok(writer->WriteTable(*table,1024));buffer.clear();bytes=0;};
            while(!queue.empty()){size_t i=queue.top();queue.pop();auto value=row(cursors[i].table,cursors[i].row);size_t n=dump(value).size();if(!buffer.empty()&&(buffer.size()>=1024||bytes+n>4*1024*1024))flush();buffer.push_back(std::move(value));bytes+=n;cursors[i].advance();if(cursors[i].table)queue.push(i);}
            flush();ok(writer->Close());ok(file->Close());count(c,"spill_write_bytes",std::filesystem::file_size(path));merged.push_back(path);
        }runs=std::move(merged);
    }
    auto file=take(arrow::io::ReadableFile::Open(runs[0].string()));auto reader=take(arrow::ipc::RecordBatchStreamReader::Open(file));
    auto result=take(reader->ToTable());count(c,"spill_read_bytes",std::filesystem::file_size(runs[0]));
    return take(result->RemoveColumn(result->num_columns()-1));
}
}
