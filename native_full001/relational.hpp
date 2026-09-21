#pragma once
#include "common.hpp"
namespace full {
inline Table filtering(Table t,const J&p,bool vectorized,Counts&c){
    std::vector<int64_t> rows;
    if(vectorized){
        for(int64_t base=0;base<t->num_rows();base+=1024){
            int64_t n=std::min<int64_t>(1024,t->num_rows()-base);std::vector<uint8_t> mask(n);
            for(int64_t j=0;j<n;++j){count(c,"predicate_evaluations");mask[j]=predicate(t,base+j,p);}
            for(int64_t j=0;j<n;++j)if(mask[j])rows.push_back(base+j);
            count(c,"vector_batches");
        }
    }else for(int64_t i=0;i<t->num_rows();++i){count(c,"predicate_evaluations");if(predicate(t,i,p))rows.push_back(i);}
    count(c,"rows_in",t->num_rows());count(c,"rows_out",rows.size());return select(t,rows);
}
inline Table topk(Table t,const J&p,bool heap,Counts&c){
    auto k=p.at("k").i();if(k<0)throw Fault("PARAMETER_RANGE","plan");
    std::vector<int> groupcols=p.has("partition_by")?columns(t,p.at("partition_by")):std::vector<int>{};
    std::map<std::string,std::vector<int64_t>> groups;Order order{t,p.at("keys"),&c};
    if(heap){
        for(int64_t i=0;i<t->num_rows();++i){
            count(c,"rows_in");auto& q=groups[key(t,i,groupcols)];if(k==0)continue;
            if(int64_t(q.size())<k){q.push_back(i);std::push_heap(q.begin(),q.end(),order);count(c,"heap_pushes");}
            else if(order(i,q.front())){std::pop_heap(q.begin(),q.end(),order);q.back()=i;std::push_heap(q.begin(),q.end(),order);count(c,"heap_replacements");}
        }
    }else for(int64_t i=0;i<t->num_rows();++i){groups[key(t,i,groupcols)].push_back(i);count(c,"rows_in");}
    std::vector<int64_t> result;
    for(auto&[_,v]:groups){std::sort(v.begin(),v.end(),order);if(int64_t(v.size())>k)v.resize(k);result.insert(result.end(),v.begin(),v.end());}
    return select(t,result);
}
inline Table sorting(Table t,const J&p,bool external,const std::string& directory,Counts&c){
    Order order{t,p.at("keys"),&c};std::vector<int64_t> output;
    if(!external){output=ordinals(t->num_rows());std::sort(output.begin(),output.end(),order);}
    else {
        // Fixed 1024-row ordinal runs; referenced Arrow input remains explicit.
        // Subsequent runtime spill uses Arrow IPC for the source payload itself.
        std::vector<std::filesystem::path> paths;
        struct Cleanup {std::vector<std::filesystem::path>& p;~Cleanup(){for(auto&f:p){std::error_code ec;std::filesystem::remove(f,ec);}}} cleanup{paths};
        for(int64_t base=0;base<t->num_rows();base+=1024){
            std::vector<int64_t> run;for(auto i=base;i<std::min(base+1024,t->num_rows());++i)run.push_back(i);
            std::sort(run.begin(),run.end(),order);auto f=std::filesystem::path(directory)/("sort-"+std::to_string(paths.size())+".run");
            if(std::filesystem::exists(f))throw Fault("EXCLUSIVE_PATH_REQUIRED");paths.push_back(f);
            std::ofstream stream(f,std::ios::binary);stream.write(reinterpret_cast<const char*>(run.data()),run.size()*sizeof(int64_t));stream.close();if(!stream)throw Fault("SPILL_WRITE_FAILED");
            count(c,"sort_runs");count(c,"spill_write_bytes",run.size()*8);
        }
        // The bounded fan-in policy is enforced by the caller's pass scheduler.
        if(paths.size()>64)throw Fault("EXTERNAL_SORT_FANIN_LIMIT");
        std::vector<std::ifstream> files;for(auto&p:paths)files.emplace_back(p,std::ios::binary);
        using Entry=std::pair<int64_t,size_t>;
        auto later=[&](const Entry&a,const Entry&b){return order(b.first,a.first);};
        std::priority_queue<Entry,std::vector<Entry>,decltype(later)> q(later);
        for(size_t i=0;i<files.size();++i){int64_t v;if(files[i].read(reinterpret_cast<char*>(&v),8))q.push({v,i});}
        while(!q.empty()){auto [v,i]=q.top();q.pop();output.push_back(v);count(c,"spill_read_bytes",8);if(files[i].read(reinterpret_cast<char*>(&v),8))q.push({v,i});else if(!files[i].eof())throw Fault("SPILL_READ_FAILED");}
        count(c,"merge_passes");
    }return select(t,output);
}
inline Table dedup(Table t,const J&p,bool hash,Counts&c){
    auto cols=columns(t,p.at("keys"));bool last=p.at("keep").str()=="last";std::vector<int64_t> indices;
    if(hash){std::unordered_map<std::string,int64_t> m;for(int64_t i=0;i<t->num_rows();++i){auto k=key(t,i,cols);count(c,"hash_probes");if(last||!m.count(k))m[k]=i;}for(auto&[_,v]:m)indices.push_back(v);}
    else {
        auto v=ordinals(t->num_rows());auto less=[&](int64_t a,int64_t b){count(c,"key_comparisons");auto ka=key(t,a,cols),kb=key(t,b,cols);return ka==kb?a<b:ka<kb;};std::sort(v.begin(),v.end(),less);
        for(size_t i=0;i<v.size();){size_t j=i+1;while(j<v.size()&&key(t,v[i],cols)==key(t,v[j],cols))++j;indices.push_back(v[last?j-1:i]);i=j;}
    }std::sort(indices.begin(),indices.end());count(c,"distinct_keys",indices.size());return select(t,indices);
}
inline Table joining(Table l,Table r,const J&p,const std::string& impl,Counts&c){
    std::vector<int> lc,rc;for(auto&k:p.at("keys").arr()){lc.push_back(l->schema()->GetFieldIndex(k.at("left").str()));rc.push_back(r->schema()->GetFieldIndex(k.at("right").str()));}
    std::vector<std::pair<int64_t,int64_t>> pairs;std::vector<bool> lm(l->num_rows()),rm(r->num_rows());
    auto emit=[&](int64_t i,int64_t j){pairs.emplace_back(i,j);lm[i]=true;rm[j]=true;};
    if(impl=="hash"){
        bool left=p.at("build_side").str()=="left";auto b=left?l:r,probe=left?r:l;auto bc=left?lc:rc,pc=left?rc:lc;
        std::unordered_map<std::string,std::vector<int64_t>> index;
        for(int64_t i=0;i<b->num_rows();++i){bool null=false;auto k=key(b,i,bc,&null);if(!null)index[k].push_back(i);count(c,"build_rows");}
        for(int64_t i=0;i<probe->num_rows();++i){bool null=false;auto k=key(probe,i,pc,&null);count(c,"hash_probes");if(null)continue;auto f=index.find(k);if(f!=index.end())for(auto j:f->second)emit(left?j:i,left?i:j);}
    }else if(impl=="sort_merge"){
        auto a=ordinals(l->num_rows()),b=ordinals(r->num_rows());
        auto sorter=[&](Table t,const std::vector<int>& cols){return [&,t,cols](int64_t i,int64_t j){count(c,"key_comparisons");return key(t,i,cols)<key(t,j,cols);};};
        std::stable_sort(a.begin(),a.end(),sorter(l,lc));std::stable_sort(b.begin(),b.end(),sorter(r,rc));
        size_t i=0,j=0;while(i<a.size()&&j<b.size()){
            bool an=false,bn=false;auto x=key(l,a[i],lc,&an),y=key(r,b[j],rc,&bn);count(c,"key_comparisons");
            if(an){++i;continue;}if(bn){++j;continue;}if(x<y){++i;continue;}if(y<x){++j;continue;}
            size_t ie=i+1,je=j+1;while(ie<a.size()&&key(l,a[ie],lc)==x)++ie;while(je<b.size()&&key(r,b[je],rc)==y)++je;
            for(size_t u=i;u<ie;++u)for(size_t v=j;v<je;++v)emit(a[u],b[v]);i=ie;j=je;
        }
    }else if(impl=="block_nested"){
        for(int64_t base=0;base<l->num_rows();base+=32)for(int64_t j=0;j<r->num_rows();++j)for(int64_t i=base;i<std::min(base+32,l->num_rows());++i){bool an=false,bn=false;auto a=key(l,i,lc,&an),b=key(r,j,rc,&bn);count(c,"pairs_considered");if(!an&&!bn&&a==b)emit(i,j);}
    }else throw Fault("UNSUPPORTED_IMPLEMENTATION");
    auto mode=p.at("join_type").str();
    if(mode=="semi"||mode=="anti"){std::vector<int64_t> rows;for(int64_t i=0;i<l->num_rows();++i)if(lm[i]==(mode=="semi"))rows.push_back(i);return select(l,rows);}
    if(mode=="left"||mode=="full")for(int64_t i=0;i<l->num_rows();++i)if(!lm[i])pairs.emplace_back(i,-1);
    if(mode=="right"||mode=="full")for(int64_t j=0;j<r->num_rows();++j)if(!rm[j])pairs.emplace_back(-1,j);
    std::sort(pairs.begin(),pairs.end());std::vector<std::shared_ptr<arrow::Field>> fields;
    for(auto&f:l->schema()->fields())fields.push_back(f->WithName("left."+f->name()));for(auto&f:r->schema()->fields())fields.push_back(f->WithName("right."+f->name()));
    J::A rows;for(auto[i,j]:pairs){J::O v;for(int z=0;z<l->num_columns();++z)v["left."+l->field(z)->name()]=i<0?J(nullptr):cell(l,z,i);for(int z=0;z<r->num_columns();++z)v["right."+r->field(z)->name()]=j<0?J(nullptr):cell(r,z,j);rows.push_back(v);}
    count(c,"rows_out",rows.size());return from_rows(rows,arrow::schema(fields));
}
inline Table aggregate(Table t,const J&p,bool hash,Counts&c){
    auto cols=columns(t,p.at("group_by"));std::vector<std::vector<int64_t>> groups;
    if(hash){std::unordered_map<std::string,size_t> index;for(int64_t i=0;i<t->num_rows();++i){auto k=key(t,i,cols);count(c,"hash_probes");if(!index.count(k)){index[k]=groups.size();groups.emplace_back();}groups[index[k]].push_back(i);}}
    else {auto rows=ordinals(t->num_rows());std::stable_sort(rows.begin(),rows.end(),[&](int64_t i,int64_t j){count(c,"key_comparisons");return key(t,i,cols)<key(t,j,cols);});std::string prior;for(auto i:rows){auto k=key(t,i,cols);if(groups.empty()||k!=prior){groups.emplace_back();prior=k;}groups.back().push_back(i);}}
    if(cols.empty()&&groups.empty())groups.emplace_back();
    std::vector<std::shared_ptr<arrow::Field>> fields;for(auto col:cols)fields.push_back(t->field(col));
    for(auto&s:p.at("aggregates").arr()){auto fn=s.at("function").str();auto type=fn=="count"?arrow::int64():fn=="mean"?arrow::float64():t->field(t->schema()->GetFieldIndex(s.at("field").str()))->type();fields.push_back(arrow::field(s.at("as").str(),type));}
    J::A result;for(auto& g:groups){J::O out;for(auto col:cols)out[t->field(col)->name()]=cell(t,col,g.front());
        for(auto&s:p.at("aggregates").arr()){
            auto fn=s.at("function").str();J acc=nullptr;int64_t n=0;
            for(auto i:g){J v=s.at("field").null()?J(1):field(t,i,s.at("field").str());if(v.null())continue;++n;count(c,"values_accumulated");
                if(fn=="count")continue;if(acc.null())acc=fn=="mean"?J(v.d()):v;
                else if(fn=="sum"||fn=="mean")acc=arithmetic("add",acc,v);
                else if((fn=="min"&&compare(v,acc)<0)||(fn=="max"&&compare(v,acc)>0))acc=v;
            }
            out[s.at("as").str()]=fn=="count"?J(n):fn=="mean"&&n?J(acc.d()/double(n)):acc;
        }result.push_back(out);
    }
    std::sort(result.begin(),result.end(),[&](const J&a,const J&b){J::A x,y;for(auto col:cols){auto n=t->field(col)->name();x.push_back(a.at(n));y.push_back(b.at(n));}return dump(x)<dump(y);});
    count(c,"groups",groups.size());return from_rows(result,arrow::schema(fields));
}
}
