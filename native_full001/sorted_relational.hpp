#pragma once
#include "bounded.hpp"
namespace full {

inline std::tuple<std::string,int64_t,Counts> sorted_group_file(const std::string&input,const J&p,const std::string&directory){
    SpillCursor cursor(input);auto schema=cursor.reader->schema();Counts counts;
    std::vector<std::shared_ptr<arrow::Field>> fields;
    for(auto&k:p.at("group_by").arr())fields.push_back(schema->GetFieldByName(k.str()));
    for(auto&a:p.at("aggregates").arr()){
        auto fn=a.at("function").str();auto type=fn=="count"?arrow::int64():fn=="mean"?arrow::float64():schema->GetFieldByName(a.at("field").str())->type();
        fields.push_back(arrow::field(a.at("as").str(),type,fn!="count"));
    }
    auto output=(std::filesystem::path(directory)/"grouped.arrowstream").string();SpillWriter writer(output,arrow::schema(fields));
    struct Acc{J value=nullptr;int64_t count=0;};std::vector<Acc> acc(p.at("aggregates").arr().size());
    J::O group;std::string previous;bool active=false;
    auto flush=[&](){
        if(!active)return;J::O out=group;
        for(size_t i=0;i<acc.size();++i){auto&a=p.at("aggregates").arr()[i];auto fn=a.at("function").str();
            out[a.at("as").str()]=fn=="count"?J(acc[i].count):fn=="mean"&&acc[i].count?J(acc[i].value.d()/double(acc[i].count)):acc[i].value;}
        writer.append(out);count(counts,"groups");acc=std::vector<Acc>(acc.size());
    };
    if(p.at("group_by").arr().empty()){active=true;previous="[]";}
    while(cursor.table){
        auto value=cursor.value();J::A keys;for(auto&k:p.at("group_by").arr())keys.push_back(value.at(k.str()));auto key=dump(keys);
        if(!active||previous!=key){flush();group.clear();for(auto&k:p.at("group_by").arr())group[k.str()]=value.at(k.str());previous=key;active=true;}
        for(size_t i=0;i<acc.size();++i){auto&a=p.at("aggregates").arr()[i];auto fn=a.at("function").str();auto v=a.at("field").null()?J(1):value.at(a.at("field").str());
            if(v.null())continue;if(acc[i].count==INT64_MAX)throw Fault("ARITHMETIC_OVERFLOW","plan");++acc[i].count;count(counts,"values_accumulated");
            if(fn=="count")continue;
            if(acc[i].value.null())acc[i].value=fn=="mean"?J(v.d()):v;
            else if(fn=="sum"||fn=="mean")acc[i].value=arithmetic("add",acc[i].value,v);
            else if((fn=="min"&&compare(v,acc[i].value)<0)||(fn=="max"&&compare(v,acc[i].value)>0))acc[i].value=v;
        }
        count(counts,"rows_in");cursor.advance();
    }
    flush();writer.finish();count(counts,"peak_group_states",1);count(counts,"retained_input_rows",0);
    return {output,writer.rows,counts};
}

inline std::tuple<std::string,int64_t,Counts> sorted_join_files(const std::string&left,const std::string&right,const J&p,const std::string&directory){
    SpillCursor l(left),r(right);auto ls=l.reader->schema(),rs=r.reader->schema();auto mode=p.at("join_type").str();Counts counts;
    bool only_left=mode=="semi"||mode=="anti";std::vector<std::shared_ptr<arrow::Field>> fields;
    auto name=[&](const std::string&side,const std::string&field){return ls->GetFieldIndex(field)>=0&&rs->GetFieldIndex(field)>=0?side+"."+field:field;};
    for(auto&f:ls->fields())fields.push_back(only_left?f:f->WithName(name("left",f->name()))->WithNullable(f->nullable()||mode=="right"||mode=="full"));
    if(!only_left)for(auto&f:rs->fields())fields.push_back(f->WithName(name("right",f->name()))->WithNullable(f->nullable()||mode=="left"||mode=="full"));
    auto output=(std::filesystem::path(directory)/"joined.arrowstream").string();SpillWriter writer(output,arrow::schema(fields));
    auto emit=[&](const J&a,const J&b){
        if(only_left){writer.append(a);return;}J::O row;
        for(auto&f:ls->fields())row[name("left",f->name())]=a.null()?J(nullptr):a.at(f->name());
        for(auto&f:rs->fields())row[name("right",f->name())]=b.null()?J(nullptr):b.at(f->name());
        writer.append(row);
    };
    auto unmatched_left=[&](const J&v){if(mode=="left"||mode=="full"||mode=="anti")emit(v,nullptr);};
    auto unmatched_right=[&](const J&v){if(mode=="right"||mode=="full")emit(nullptr,v);};
    auto keys=[&](const J&v,const std::string&side){J::A result;for(auto&k:p.at("keys").arr())result.push_back(v.at(k.at(side).str()));return result;};
    auto has_null=[](const J::A&v){return std::any_of(v.begin(),v.end(),[](const J&x){return x.null();});};
    auto cmp=[&](const J::A&a,const J::A&b){count(counts,"key_comparisons");for(size_t i=0;i<a.size();++i){
        if(a[i].null()||b[i].null()){if(a[i].null()&&b[i].null())continue;return a[i].null()?1:-1;}
        int c=compare(a[i],b[i]);if(c)return c;}return 0;};
    int64_t group_id=0;
    while(l.table&&r.table){
        auto a=l.value(),b=r.value();auto ka=keys(a,"left"),kb=keys(b,"right");int order=cmp(ka,kb);
        if(order<0||has_null(ka)){unmatched_left(a);l.advance();continue;}
        if(order>0||has_null(kb)){unmatched_right(b);r.advance();continue;}
        auto group=(std::filesystem::path(directory)/("join-group-"+std::to_string(group_id++)+".arrowstream")).string();
        {SpillWriter spool(group,rs);do{spool.append(r.value());r.advance();}while(r.table&&cmp(keys(r.value(),"right"),kb)==0);spool.finish();}
        do{
            if(mode=="semi")emit(l.value(),nullptr);
            else if(mode!="anti"){
                SpillCursor duplicates(group);while(duplicates.table){emit(l.value(),duplicates.value());count(counts,"pairs_emitted");duplicates.advance();}
            }
            l.advance();
        }while(l.table&&cmp(keys(l.value(),"left"),ka)==0);
        std::filesystem::remove(group);
    }
    while(l.table){unmatched_left(l.value());l.advance();}
    while(r.table){unmatched_right(r.value());r.advance();}
    writer.finish();count(counts,"peak_join_cursors",3);count(counts,"rows_out",writer.rows);
    return {output,writer.rows,counts};
}
}
