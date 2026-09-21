#pragma once
#include "common.hpp"
namespace full {
struct Graph {
    J source;std::vector<J> nodes,edges;std::unordered_map<std::string,size_t> lookup;
    std::vector<std::vector<std::pair<size_t,size_t>>> adjacency;
    std::vector<size_t> offsets,targets,edge_indices;
    std::string node_field,source_field,target_field;
    explicit Graph(const J&g,const std::string& direction="out",bool csr=false,const J&fields=J::O{}):source(g),nodes(g.at("nodes").arr()),edges(g.at("edges").arr()),
        node_field(fields.has("node_id_field")?fields.at("node_id_field").str():"node_id"),source_field(fields.has("source_field")?fields.at("source_field").str():"src"),target_field(fields.has("target_field")?fields.at("target_field").str():"dst"){
        for(size_t i=0;i<nodes.size();++i){auto k=dump(nodes[i].at(node_field));if(lookup.count(k))throw Fault("DUPLICATE_NODE");lookup[k]=i;}
        adjacency.resize(nodes.size());std::unordered_set<std::string> ids;
        bool directed=g.has("directed")?g.at("directed").b():true;
        for(size_t i=0;i<edges.size();++i){auto&e=edges[i];auto a=lookup.find(dump(e.at(source_field))),b=lookup.find(dump(e.at(target_field)));
            if(a==lookup.end()||b==lookup.end())throw Fault("UNKNOWN_ENDPOINT");if(e.has("edge_id")&&!ids.insert(dump(e.at("edge_id"))).second)throw Fault("DUPLICATE_EDGE_ID");
            if(direction!="in"||!directed)adjacency[a->second].push_back({b->second,i});
            if(direction!="out"||!directed)if(a->second!=b->second||direction=="in")adjacency[b->second].push_back({a->second,i});
        }
        if(csr){offsets.push_back(0);for(auto&a:adjacency){for(auto[v,e]:a){targets.push_back(v);edge_indices.push_back(e);}offsets.push_back(targets.size());}adjacency.clear();}
    }
    size_t id(const J&v)const{auto f=lookup.find(dump(v));if(f==lookup.end())throw Fault("UNKNOWN_SEED","plan");return f->second;}
    template<class Fn>void neighbors(size_t n,Fn fn)const{
        if(!offsets.empty())for(size_t i=offsets[n];i<offsets[n+1];++i)fn(targets[i],edge_indices[i]);
        else for(auto[v,e]:adjacency[n])fn(v,e);
    }
};
inline J graph_kernel(const std::string&op,const std::string&impl,const J&g,const J&seeds,const J&p,Counts&c){
    auto direction=p.has("direction")?p.at("direction").str():"out";
    Graph graph(g,direction,impl=="csr",p.has("_graph_fields")?p.at("_graph_fields"):J(J::O{}));J::A out;
    if(op=="graph_neighbors"){
        std::unordered_set<size_t> found;
        for(auto&s:seeds.arr()){auto n=graph.id(s);count(c,"adjacency_lookups");graph.neighbors(n,[&](size_t,size_t e){count(c,"edge_visits");auto&edge=graph.edges[e];bool allowed=p.at("edge_types").arr().empty();for(auto&t:p.at("edge_types").arr())if(compare(t,edge.at("type"))==0)allowed=true;if(allowed&&found.insert(e).second)out.push_back(edge);});}return out;
    }
    if(op=="graph_reachability"){
        auto hops=p.at("max_hops").i();std::vector<int64_t> depth(graph.nodes.size(),INT64_MAX);std::deque<std::pair<size_t,int64_t>> pending;
        for(auto&s:seeds.arr()){auto n=graph.id(s);depth[n]=0;pending.push_back({n,0});}
        while(!pending.empty()){
            auto item=impl=="dfs"?pending.back():pending.front();if(impl=="dfs")pending.pop_back();else pending.pop_front();
            auto[n,d]=item;if(d!=depth[n])continue;count(c,"state_expansions");if(d>=hops)continue;
            graph.neighbors(n,[&](size_t v,size_t){count(c,"edge_visits");if(d+1<depth[v]){depth[v]=d+1;pending.push_back({v,d+1});}});
        }
        for(size_t i=0;i<depth.size();++i)if(depth[i]!=INT64_MAX)out.push_back(graph.nodes[i].at(graph.node_field));return out;
    }
    if(op=="graph_shortest_path"){
        auto weight=p.at("weight_field");double equal=-1;
        for(auto&e:graph.edges){if(!e.has("edge_id"))throw Fault("STABLE_EDGE_ID_REQUIRED","plan");double w=weight.null()?1:e.at(weight.str()).d();if(w<0||!std::isfinite(w))throw Fault("NEGATIVE_WEIGHT","plan");if(equal<0)equal=w;else if(impl=="bfs"&&w!=equal)throw Fault("BFS_REQUIRES_EQUAL_WEIGHTS","plan");}
        std::vector<double> dist(graph.nodes.size(),std::numeric_limits<double>::infinity());std::vector<int64_t> parent(graph.nodes.size(),-1),parent_edge(graph.nodes.size(),-1);
        using Item=std::pair<double,size_t>;std::priority_queue<Item,std::vector<Item>,std::greater<Item>> heap;std::deque<size_t> queue;
        for(auto&s:seeds.arr()){auto n=graph.id(s);dist[n]=0;heap.push({0,n});queue.push_back(n);}
        while(impl=="bfs"?!queue.empty():!heap.empty()){
            size_t n;if(impl=="bfs"){n=queue.front();queue.pop_front();}else {auto[d,v]=heap.top();heap.pop();count(c,"heap_operations");if(d!=dist[v])continue;n=v;}
            graph.neighbors(n,[&](size_t v,size_t ei){count(c,"edge_visits");double w=weight.null()?1:graph.edges[ei].at(weight.str()).d();double next=dist[n]+w;if(!std::isfinite(next))throw Fault("DISTANCE_OVERFLOW","plan");
                if(next<dist[v]){dist[v]=next;parent[v]=int64_t(n);parent_edge[v]=int64_t(ei);count(c,"relaxations");if(impl=="bfs")queue.push_back(v);else {heap.push({next,v});count(c,"heap_operations");}}
            });
        }
        J::A target=p.at("target").array()?p.at("target").arr():J::A{p.at("target")};
        for(auto&t:target){auto v=graph.id(t);J::A ns,es;bool reachable=std::isfinite(dist[v]);
            if(reachable){for(int64_t n=int64_t(v);n>=0;n=parent[n]){ns.push_back(graph.nodes[n].at(graph.node_field));if(parent_edge[n]>=0)es.push_back(graph.edges[parent_edge[n]].at("edge_id"));if(ns.size()>graph.nodes.size())throw Fault("PATH_CYCLE_INTERNAL");}std::reverse(ns.begin(),ns.end());std::reverse(es.begin(),es.end());}
            out.push_back(J::O{{"target",t},{"reachable",reachable},{"distance",reachable?J(dist[v]):J(nullptr)},{"nodes",ns},{"edges",es}});
        }return out;
    }
    if(op=="graph_filter"){
        std::function<bool(const J&)> node_reference=[&](const J&v){
            if(v.object()){if(v.has("field")&&v.at("field").str().rfind("node.",0)==0)return true;for(auto&[_,child]:v.obj())if(node_reference(child))return true;}
            if(v.array())for(auto&child:v.arr())if(node_reference(child))return true;
            return false;
        };bool has_node=node_reference(p.at("predicate"));
        std::vector<size_t> candidates(graph.edges.size());std::iota(candidates.begin(),candidates.end(),0);
        if(impl=="index_filter"){
            // Traverse the supplied, preparation-built index; never substitute an edge mask.
            candidates.clear();if(!g.has("edge_index"))throw Fault("INDEX_UNAVAILABLE");
            std::unordered_set<size_t> seen;for(auto&i:g.at("edge_index").arr()){auto n=size_t(i.i());if(n>=graph.edges.size()||!seen.insert(n).second)throw Fault("INDEX_INVALID");candidates.push_back(n);}if(seen.size()!=graph.edges.size())throw Fault("INDEX_INCOMPLETE");
        }
        std::vector<bool> keep(graph.edges.size());for(auto i:candidates){
            if(impl=="index_filter")count(c,"index_entries_visited");auto&edge=graph.edges[i];
            auto matches=[&](const J&endpoint){count(c,"predicate_evaluations");auto v=eval(p.at("predicate"),[&](const std::string&n){
                if(n.rfind("node.",0)==0)return graph.nodes[graph.id(endpoint)].at(n.substr(5));
                return edge.at(n.rfind("edge.",0)==0?n.substr(5):n);
            });return !v.null()&&v.b();};
            keep[i]=matches(edge.at(graph.source_field))&&(!has_node||matches(edge.at(graph.target_field)));
        }
        auto obj=g.obj();for(size_t i=0;i<keep.size();++i)if(keep[i])out.push_back(graph.edges[i]);obj["edges"]=out;obj.erase("edge_index");return obj;
    }
    if(op=="graph_subgraph"){
        std::unordered_set<std::string> chosen,ends;for(auto&s:seeds.arr())chosen.insert(dump(s));
        if(impl=="induced"){for(auto&s:seeds.arr())graph.id(s);ends=chosen;for(auto&e:graph.edges)if(chosen.count(dump(e.at(graph.source_field)))&&chosen.count(dump(e.at(graph.target_field))))out.push_back(e);}
        else {for(auto&e:graph.edges){if(!e.has("edge_id"))throw Fault("STABLE_EDGE_ID_REQUIRED","plan");if(chosen.erase(dump(e.at("edge_id")))){out.push_back(e);ends.insert(dump(e.at(graph.source_field)));ends.insert(dump(e.at(graph.target_field)));}}if(!chosen.empty())throw Fault("FOREIGN_EDGE_ID","plan");}
        J::A nodes;for(auto&n:graph.nodes)if(ends.count(dump(n.at(graph.node_field))))nodes.push_back(n);auto obj=g.obj();obj["nodes"]=nodes;obj["edges"]=out;obj.erase("edge_index");return obj;
    }
    throw Fault("UNSUPPORTED_IMPLEMENTATION");
}
inline J set_kernel(const J&l,const J&r,const std::string&mode,bool hash,Counts&c){
    std::vector<std::string>a,b,out;std::unordered_map<std::string,J> original;
    for(auto&v:l.arr()){auto k=dump(v);a.push_back(k);original[k]=v;}for(auto&v:r.arr()){auto k=dump(v);b.push_back(k);original[k]=v;}
    if(hash){std::unordered_set<std::string>x(a.begin(),a.end()),y(b.begin(),b.end());for(auto&k:x){count(c,"hash_probes");if(mode=="union"||(mode=="intersection"&&y.count(k))||(mode=="difference"&&!y.count(k)))out.push_back(k);}if(mode=="union")for(auto&k:y)if(!x.count(k))out.push_back(k);std::sort(out.begin(),out.end());}
    else {std::sort(a.begin(),a.end());std::sort(b.begin(),b.end());a.erase(std::unique(a.begin(),a.end()),a.end());b.erase(std::unique(b.begin(),b.end()),b.end());auto less=[&](const auto&x,const auto&y){count(c,"key_comparisons");return x<y;};if(mode=="union")std::set_union(a.begin(),a.end(),b.begin(),b.end(),std::back_inserter(out),less);else if(mode=="intersection")std::set_intersection(a.begin(),a.end(),b.begin(),b.end(),std::back_inserter(out),less);else std::set_difference(a.begin(),a.end(),b.begin(),b.end(),std::back_inserter(out),less);}
    J::A result;for(auto&k:out)result.push_back(original.at(k));return result;
}
inline J dense(const J&docs,const J&query,const J&p,Counts&c){
    std::vector<std::pair<double,std::string>> ranked;std::unordered_map<std::string,J> ids;
    for(auto&d:docs.arr()){auto& v=d.at("vector").arr();if(v.size()!=query.arr().size())throw Fault("VECTOR_DIMENSION");double score=0;for(size_t i=0;i<v.size();++i)score+=v[i].d()*query.arr()[i].d();if(!std::isfinite(score))throw Fault("NONFINITE");auto k=dump(d.at("document_id"));ranked.push_back({score,k});ids[k]=d.at("document_id");count(c,"dot_products");}
    std::sort(ranked.begin(),ranked.end(),[](auto&a,auto&b){return a.first==b.first?a.second<b.second:a.first>b.first;});J::A result;int64_t offset=p.has("offset")?p.at("offset").i():0,limit=p.at("limit").i();for(int64_t i=offset;i<std::min<int64_t>(offset+limit,ranked.size());++i)result.push_back(J::O{{"document_id",ids[ranked[i].second]},{"score",ranked[i].first}});return result;
}
}
