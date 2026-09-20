// NATIVE001: real, single-threaded C++17 F1 pull pipeline. No network API.
#include "json.hpp"
#include "sha256.hpp"
#include <chrono>
#include <cstdio>
#include <fcntl.h>
#include <functional>
#include <iostream>
#include <memory>
#include <queue>
#include <sys/stat.h>
#include <unistd.h>

using namespace rcwg;
#ifndef RCWG_NATIVE_DIAGNOSTICS
#error Build must explicitly set RCWG_NATIVE_DIAGNOSTICS=0 or 1
#endif
static constexpr bool instrumentation=(RCWG_NATIVE_DIAGNOSTICS==1);
static int64_t now(){return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();}
struct File {
    FILE* f=nullptr;
    explicit File(const std::string& path){
        if(path.empty()||path[0]!='/')throw Fault("DATA_ABSOLUTE_PATH_REQUIRED");
        int fd=::open("/",O_RDONLY|O_DIRECTORY|O_CLOEXEC);if(fd<0)throw Fault("DATA_OPEN_FAILED");
        size_t start=1;
        while(start<path.size()){
            auto end=path.find('/',start);auto part=path.substr(start,end==std::string::npos?end:end-start);
            if(part.empty()||part=="."||part==".."){::close(fd);throw Fault("DATA_PATH_INVALID");}
            bool last=end==std::string::npos;int flags=O_RDONLY|O_NOFOLLOW|O_CLOEXEC|O_NONBLOCK|(last?0:O_DIRECTORY);
            int next=::openat(fd,part.c_str(),flags);::close(fd);fd=next;
            if(fd<0)throw Fault("DATA_OPEN_FAILED");if(last)break;start=end+1;
        }
        struct stat st{};if(fstat(fd,&st)||!S_ISREG(st.st_mode)){::close(fd);throw Fault("DATA_NOT_REGULAR");}
        f=fdopen(fd,"rb");if(!f){::close(fd);throw Fault("DATA_OPEN_FAILED");}
    }
    ~File(){if(f)fclose(f);}File(const File&)=delete;
    bool line(std::string& out){out.clear();int c;while((c=fgetc(f))!=EOF){out.push_back(char(c));if(out.size()>1048576)throw Fault("DATA_LINE_LIMIT");if(c=='\n')break;}if(ferror(f))throw Fault("DATA_READ_FAILED");return !out.empty();}
};
struct Buffer { uint64_t id;std::vector<J> cells; };
struct Row {
    std::shared_ptr<const Buffer> backing;
    std::vector<std::pair<std::string,size_t>> columns;
    int64_t ordinal=0;
    const J& at(const std::string& k)const{for(auto& col:columns)if(col.first==k)return backing->cells.at(col.second);throw Fault("FIELD_NOT_AVAILABLE");}
};
struct Ctx {
    bool diagnostic=false;std::string run_id,request_hash;int64_t seq=0;uint64_t next_buffer=0;
    std::map<std::string,std::map<std::string,int64_t>> counts;
    J::A ownership;
    int event_fd=-1;
    void add(const std::string& id,const std::string& k,int64_t value=1){if constexpr(instrumentation){if(diagnostic)counts[id][k]+=value;}}
    void peak(const std::string& id,const std::string& k,int64_t value){if constexpr(instrumentation){if(diagnostic)counts[id][k]=std::max(counts[id][k],value);}}
    void event(const J& node,const std::string& kind){
        J record=J::O{{"sequence",seq++},{"run_id",run_id},{"request_sha256",request_hash},{"monotonic_ns",now()},{"kind",kind},{"node_id",node.at("id")},{"operator",node.at("operator")},{"implementation",node.at("implementation")}};
        std::string line=dump(record)+"\n";size_t p=0;while(p<line.size()){auto n=::write(event_fd,line.data()+p,line.size()-p);if(n<=0)throw Fault("EVENT_WRITE_FAILED");p+=size_t(n);}
    }
    void witness(const std::string& node,uint64_t from,uint64_t to,size_t cells){
        if constexpr(instrumentation){if(diagnostic&&ownership.size()<16)ownership.push_back(J::O{{"node_id",node},{"source_buffer_id",int64_t(from)},{"result_buffer_id",int64_t(to)},{"selected_cells",int64_t(cells)}});}
    }
};
static bool equal(const J& a,const J& b){
    if(a.null()||b.null())return a.null()&&b.null();
    if(a.number()&&b.number())return (a.integer()?static_cast<long double>(a.i()):static_cast<long double>(a.d()))==(b.integer()?static_cast<long double>(b.i()):static_cast<long double>(b.d()));
    if(a.boolean()&&b.boolean())return a.b()==b.b();if(a.string()&&b.string())return a.str()==b.str();
    return false;
}
static int compare_value(const J& a,const J& b){
    if(equal(a,b))return 0;
    if(a.number()&&b.number()){auto x=a.integer()?static_cast<long double>(a.i()):static_cast<long double>(a.d());auto y=b.integer()?static_cast<long double>(b.i()):static_cast<long double>(b.d());return x<y?-1:1;}
    if(a.boolean()&&b.boolean())return a.b()?1:-1;
    if(a.string()&&b.string())return std::lexicographical_compare(a.str().begin(),a.str().end(),b.str().begin(),b.str().end(),[](char x,char y){return static_cast<unsigned char>(x)<static_cast<unsigned char>(y);})?-1:1;
    throw Fault("UNSUPPORTED_IMPLEMENTATION");
}
static J arithmetic(const std::string& op,const J& a,const J& b){
    if(!a.number()||!b.number())throw Fault("UNSUPPORTED_IMPLEMENTATION");
    if(op=="div"){
        if(b.d()==0)throw Fault("DIVISION_BY_ZERO","plan");
        if(a.integer()&&b.integer()&&(a.i()>9007199254740992LL||a.i()<-9007199254740992LL||b.i()>9007199254740992LL||b.i()<-9007199254740992LL))throw Fault("UNSUPPORTED_IMPLEMENTATION");
    }
    if(a.integer()&&b.integer()&&op!="div"){
        int64_t x=a.i(),y=b.i(),lo=std::numeric_limits<int64_t>::min(),hi=std::numeric_limits<int64_t>::max();
        if(op=="add"){if((y>0&&x>hi-y)||(y<0&&x<lo-y))throw Fault("ARITHMETIC_OVERFLOW","plan");return x+y;}
        if(op=="sub"){if((y<0&&x>hi+y)||(y>0&&x<lo+y))throw Fault("ARITHMETIC_OVERFLOW","plan");return x-y;}
        if(op=="mul"){
            if((x>0&&((y>0&&x>hi/y)||(y<0&&y<lo/x)))||(x<0&&((y>0&&x<lo/y)||(y<0&&x<hi/y))))throw Fault("ARITHMETIC_OVERFLOW","plan");return x*y;
        }
    }
    double x=a.d(),y=b.d(),v;if(op=="add")v=x+y;else if(op=="sub")v=x-y;else if(op=="mul")v=x*y;else if(op=="div")v=x/y;else throw Fault("UNSUPPORTED_IMPLEMENTATION");
    if(!std::isfinite(v))throw Fault("ARITHMETIC_OVERFLOW","plan");return v;
}
static J eval(const J& ast,const Row& row){
    if(ast.has("field"))return row.at(ast.at("field").str());if(ast.has("literal"))return ast.at("literal");
    auto op=ast.at("op").str();
    if(op=="and"||op=="or"){
        bool unknown=false,yes=false,no=false;for(auto& arg:ast.at("args").arr()){auto v=eval(arg,row);if(v.null())unknown=true;else if(v.b())yes=true;else no=true;}
        if(op=="and"){if(no)return false;if(unknown)return nullptr;return true;}
        if(yes)return true;if(unknown)return nullptr;return false;
    }
    if(op=="not"||op=="is_null"||op=="count"){
        auto v=eval(ast.at("arg"),row);if(op=="is_null")return v.null();if(v.null())return nullptr;
        if(op=="not")return !v.b();if(v.string())return int64_t(utf8_count(v.str()));if(v.array())return int64_t(v.arr().size());throw Fault("UNSUPPORTED_IMPLEMENTATION");
    }
    auto a=eval(ast.at("left"),row),b=eval(ast.at("right"),row);
    if(op=="in"){
        if(b.array()&&b.arr().empty())return false;if(a.null()||b.null())return nullptr;
        bool null=false;for(auto& v:b.arr()){if(v.null())null=true;else if(equal(a,v))return true;}if(null)return nullptr;return false;
    }
    if(a.null()||b.null())return nullptr;
    if(op=="eq")return equal(a,b);if(op=="ne")return !equal(a,b);
    if(op=="lt"||op=="le"||op=="gt"||op=="ge"){int cmp=compare_value(a,b);return op=="lt"?cmp<0:op=="le"?cmp<=0:op=="gt"?cmp>0:cmp>=0;}
    return arithmetic(op,a,b);
}
static bool keep(const J& predicate,const Row& row){auto v=eval(predicate,row);return !v.null()&&v.b();}
static Row project(const Row& input,const J& columns,bool copy,Ctx& ctx,const std::string& id){
    Row r;r.ordinal=input.ordinal;
    if(copy){
        auto b=std::make_shared<Buffer>();b->id=++ctx.next_buffer;
        for(auto& c:columns.arr()){
            auto& value=input.at(c.str());r.columns.emplace_back(c.str(),b->cells.size());b->cells.push_back(value);
            ctx.add(id,"application_copy_bytes",sizeof(J)+(value.string()?value.str().size():0));
        }
        r.backing=b;ctx.add(id,"row_buffers_copied");ctx.add(id,"new_buffer_allocations");
    }else{
        r.backing=input.backing;
        for(auto& c:columns.arr()){bool found=false;for(auto& col:input.columns)if(col.first==c.str()){r.columns.push_back(col);found=true;break;}if(!found)throw Fault("FIELD_NOT_AVAILABLE");}
        ctx.add(id,"row_views_created");
    }
    ctx.witness(id,input.backing->id,r.backing->id,r.columns.size());return r;
}
class Stream {
protected:
    Ctx& ctx;J node;std::string id;bool started=false,ended=false;
    virtual bool pull(Row& row)=0;
public:
    Stream(Ctx& c,J n):ctx(c),node(std::move(n)),id(node.at("id").str()){}
    virtual ~Stream()=default;
    bool next(Row& r){if(ended)return false;if(!started){ctx.event(node,"node_started");started=true;}bool ok=pull(r);if(!ok){ctx.event(node,"node_finished");ended=true;}return ok;}
};
class Scan:public Stream {
    File file;J schema;std::string expected;int64_t expected_rows,ordinal=0;SHA256 hash;
    void check(const J& v,const J& type){
        auto t=type.at("kind").str();bool nullable=type.at("nullable").b();if(v.null()){if(!nullable)throw Fault("DATA_TYPE_MISMATCH");return;}
        bool valid=(t=="Bool"&&v.boolean())||(t=="Int64"&&v.integer())||(t=="Float64"&&v.v.index()==3)||(t=="Utf8"&&v.string());if(!valid)throw Fault("DATA_TYPE_MISMATCH");
    }
    bool pull(Row& row)override{
        std::string line;
        while(file.line(line)){
            hash.update(line);ctx.add(id,"logical_read_bytes",line.size());auto parsed=Parser(line).parse();
            if(parsed.obj().size()!=schema.obj().size())throw Fault("DATA_SCHEMA_MISMATCH");
            auto b=std::make_shared<Buffer>();b->id=++ctx.next_buffer;Row input;input.ordinal=ordinal++;
            for(auto& kv:schema.obj()){auto& value=parsed.at(kv.first);check(value,kv.second);input.columns.emplace_back(kv.first,b->cells.size());b->cells.push_back(value);}
            input.backing=b;ctx.add(id,"rows_scanned");ctx.add(id,"row_buffers_allocated");
            auto& params=node.at("params");if(params.has("predicate")&&!keep(params.at("predicate"),input))continue;
            row=project(input,params.at("columns"),false,ctx,id);return true;
        }
        if(hash.finish()!=expected)throw Fault("DATA_CHANGED_DURING_RUN");if(expected_rows>=0&&ordinal!=expected_rows)throw Fault("DATA_ROW_COUNT_MISMATCH");ctx.add(id,"source_eof_verified");return false;
    }
public:
    Scan(Ctx& c,J n,const J& source):Stream(c,std::move(n)),file(source.at("path").str()),schema(source.at("schema")),expected(source.at("sha256").str()),expected_rows(source.at("row_count").null()?-1:source.at("row_count").i()){}
};
class Filter:public Stream {
    std::shared_ptr<Stream> input;std::vector<Row> batch;std::vector<unsigned char> mask;size_t pos=0,limit;
    bool pull(Row& row)override{
        auto& predicate=node.at("params").at("predicate");
        if(node.at("implementation").str()=="scalar"){
            while(input->next(row)){ctx.add(id,"predicate_evaluations");if(keep(predicate,row))return true;}return false;
        }
        while(true){
            while(pos<batch.size()){size_t i=pos++;if(mask[i]){row=std::move(batch[i]);return true;}batch[i]=Row{};}
            batch.clear();mask.clear();pos=0;Row r;while(batch.size()<limit&&input->next(r)){batch.push_back(std::move(r));}
            if(batch.empty())return false;ctx.add(id,"vector_batches");ctx.peak(id,"batch_frames_peak",batch.size());
            for(auto& item:batch){ctx.add(id,"predicate_evaluations");mask.push_back(keep(predicate,item)?1:0);}
        }
    }
public:Filter(Ctx& c,J n,std::shared_ptr<Stream> p):Stream(c,std::move(n)),input(std::move(p)),limit(node.at("batch_rows").i()){if(limit<1||limit>4096)throw Fault("UNSUPPORTED_IMPLEMENTATION");}
};
class Project:public Stream {
    std::shared_ptr<Stream> input;
    bool pull(Row& row)override{Row r;if(!input->next(r))return false;row=project(r,node.at("params").at("columns"),node.at("implementation").str()=="copy",ctx,id);return true;}
public:Project(Ctx& c,J n,std::shared_ptr<Stream> p):Stream(c,std::move(n)),input(std::move(p)){}
};
class Top:public Stream {
    std::shared_ptr<Stream> input;std::vector<Row> chosen;size_t pos=0;bool loaded=false;int64_t cap;
    bool better(const Row& a,const Row& b){
        ctx.add(id,"ordering_comparisons");
        for(auto& key:node.at("params").at("keys").arr()){
            ctx.add(id,"key_comparisons");auto& x=a.at(key.at("field").str());auto& y=b.at(key.at("field").str());
            if(x.null()||y.null()){if(x.null()&&y.null())continue;bool first=key.has("nulls")&&key.at("nulls").str()=="first";return x.null()?first:!first;}
            int cmp=compare_value(x,y);if(cmp)return key.at("direction").str()=="asc"?cmp<0:cmp>0;
        }
        return a.ordinal<b.ordinal;
    }
    bool pull(Row& row)override{
        if(!loaded){
            loaded=true;int64_t k=node.at("params").at("k").i();if(k<0||k>cap)throw Fault("NATIVE_MATERIALIZATION_CAP");Row r;
            auto less=[this](const Row& a,const Row& b){return better(a,b);};
            if(node.at("implementation").str()=="full_sort"){
                while(input->next(r)){if(chosen.size()>=size_t(cap))throw Fault("NATIVE_MATERIALIZATION_CAP");chosen.push_back(std::move(r));ctx.add(id,"input_rows");}
                ctx.peak(id,"candidate_frames_peak",chosen.size());std::sort(chosen.begin(),chosen.end(),less);ctx.add(id,"full_sort_calls");if(chosen.size()>size_t(k))chosen.resize(size_t(k));
            }else{
                while(input->next(r)){
                    ctx.add(id,"input_rows");if(k==0)continue;
                    if(chosen.size()<size_t(k)){chosen.push_back(std::move(r));std::push_heap(chosen.begin(),chosen.end(),less);ctx.add(id,"heap_pushes");}
                    else if(better(r,chosen.front())){std::pop_heap(chosen.begin(),chosen.end(),less);chosen.back()=std::move(r);std::push_heap(chosen.begin(),chosen.end(),less);ctx.add(id,"heap_replacements");}
                }
                ctx.peak(id,"candidate_frames_peak",chosen.size());std::sort(chosen.begin(),chosen.end(),less);ctx.add(id,"heap_selection_calls");
            }
            ctx.add(id,"output_rows",chosen.size());
        }
        if(pos>=chosen.size())return false;row=std::move(chosen[pos++]);return true;
    }
public:Top(Ctx& c,J n,std::shared_ptr<Stream> p,int64_t maxrows):Stream(c,std::move(n)),input(std::move(p)),cap(maxrows){}
};
static int output_fd(const char* name){int fd=::open(name,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);if(fd<0)throw Fault("OUTPUT_EXCLUSIVE_CREATE_FAILED");return fd;}
static void write_all(int fd,const std::string& s){size_t p=0;while(p<s.size()){auto n=::write(fd,s.data()+p,s.size()-p);if(n<=0)throw Fault("OUTPUT_WRITE_FAILED");p+=size_t(n);}}
int main(int argc,char** argv){
    static_assert(std::numeric_limits<long double>::digits>=64,"Exact Int64 comparison requires at least 64 mantissa bits");
    if(argc==2&&std::string(argv[1])=="--sha256"){SHA256 h;char buf[8192];while(std::cin){std::cin.read(buf,sizeof(buf));h.update(buf,size_t(std::cin.gcount()));}std::cout<<h.finish()<<'\n';return 0;}
    if(argc==2&&std::string(argv[1])=="--json"){try{std::string s((std::istreambuf_iterator<char>(std::cin)),{});std::cout<<dump(Parser(s).parse());return 0;}catch(const Fault& f){std::cerr<<f.what();return 2;}}
    int64_t start=now();Ctx ctx;J::O report;int result_fd=-1;
    try{
        std::string raw,line;while(std::getline(std::cin,line)){raw+=line+'\n';if(raw.size()>2097152)throw Fault("REQUEST_SIZE_CAP");}
        J request=Parser(raw).parse();ctx.request_hash=sha(raw);ctx.run_id=request.at("run_id").str();ctx.diagnostic=instrumentation&&request.at("mode").str()=="diagnostic";
        if((request.at("mode").str()=="diagnostic")!=instrumentation)throw Fault("BINARY_MODE_MISMATCH");
        if(request.at("revision").str()!="NATIVE001_REQUEST_V1")throw Fault("UNSUPPORTED_IMPLEMENTATION");
        if(ctx.run_id.empty()||ctx.run_id.size()>80||ctx.run_id.find_first_not_of("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")!=std::string::npos)throw Fault("RUN_ID_INVALID");
        ctx.event_fd=output_fd("worker.events.jsonl");
        auto& nodes=request.at("nodes").arr();if(nodes.size()<2||nodes.size()>128)throw Fault("UNSUPPORTED_IMPLEMENTATION");
        std::shared_ptr<Stream> stream;
        for(size_t i=0;i<nodes.size();++i){auto& n=nodes[i];auto op=n.at("operator").str(),impl=n.at("implementation").str();
            if(op=="scan"&&impl=="sequential"&&i==0)stream=std::make_shared<Scan>(ctx,n,request.at("source"));
            else if(op=="filter"&&(impl=="scalar"||impl=="vectorized")&&stream)stream=std::make_shared<Filter>(ctx,n,stream);
            else if(op=="project"&&(impl=="column_view"||impl=="copy")&&stream)stream=std::make_shared<Project>(ctx,n,stream);
            else if(op=="top_k"&&(impl=="full_sort"||impl=="streaming_heap")&&stream)stream=std::make_shared<Top>(ctx,n,stream,request.at("max_materialized_rows").i());
            else if(op=="emit"&&impl=="json_artifact"&&i==nodes.size()-1&&stream){
                ctx.event(n,"node_started");result_fd=output_fd("result.json");write_all(result_fd,"[");Row row;int64_t nrows=0,bytes=1;
                while(stream->next(row)){
                    if(nrows>=request.at("max_materialized_rows").i())throw Fault("NATIVE_MATERIALIZATION_CAP");J::O object;for(auto& c:row.columns)object.emplace(c.first,row.backing->cells[c.second]);std::string encoded=(nrows?",":"")+dump(object);write_all(result_fd,encoded);bytes+=encoded.size();++nrows;
                }
                write_all(result_fd,"]");++bytes;if(::fsync(result_fd))throw Fault("OUTPUT_FSYNC_FAILED");::close(result_fd);result_fd=-1;ctx.add(n.at("id").str(),"rows_received",nrows);ctx.event(n,"node_finished");
                report["rows"]=nrows;report["serialized_bytes"]=bytes;
            }else throw Fault("UNSUPPORTED_IMPLEMENTATION");
        }
        if(nodes.back().at("operator").str()!="emit")throw Fault("UNSUPPORTED_IMPLEMENTATION");
        report["terminal_status"]="COMPLETED";report["failure"]=nullptr;
    }catch(const Fault& f){report["terminal_status"]=f.attribution=="plan"?"MODEL_FAILURE":"INFRA_FAILURE";report["failure"]=J::O{{"code",f.what()},{"attribution",f.attribution}};}
    catch(const std::bad_alloc&){report["terminal_status"]="INFRA_FAILURE";report["failure"]=J::O{{"code","ALLOCATION_FAILURE_WITHOUT_OOM_ATTESTATION"},{"attribution","facility"}};}
    catch(const std::exception&){report["terminal_status"]="INFRA_FAILURE";report["failure"]=J::O{{"code","NATIVE_INTERNAL_ERROR"},{"attribution","facility"}};}
    if(result_fd>=0)::close(result_fd);if(ctx.event_fd>=0){::fsync(ctx.event_fd);::close(ctx.event_fd);}
    J::O counters;for(auto& n:ctx.counts){J::O c;for(auto& v:n.second)c[v.first]=v.second;counters[n.first]=c;}
    report["run_id"]=ctx.run_id;report["request_sha256"]=ctx.request_hash;report["worker_exec_wall_ns"]=now()-start;report["node_counters"]=ctx.diagnostic?J(counters):J(nullptr);report["ownership_witness"]=ctx.diagnostic?J(ctx.ownership):J(nullptr);report["diagnostic_instrumentation"]=ctx.diagnostic;report["formal_ready"]=false;
    std::cout<<dump(report)<<'\n';return report["terminal_status"].str()=="COMPLETED"?0:2;
}
