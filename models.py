
import torch
from torch.nn import init
import torch.nn as nn
import torch.nn.functional as F

class OneTower(nn.Module):
    def __init__(self, corpus_size, input_embedding_dim, hidden_dim1, 
                item_embedding_dim, sparse, single_layer = False, entity_type = 'page', normalize = False,
                temperature = 1, two_tower = False
                ):
        super(OneTower, self).__init__()
        self.normalize = normalize
        self.temperature = temperature
        self.entity_type = entity_type
        self.two_tower = two_tower
        self.corpus_size = corpus_size
        if self.entity_type == 'page':
            self.input_embeddings = nn.Embedding(corpus_size, input_embedding_dim, sparse=sparse)
            if not self.two_tower:
                self.item_embeddings = nn.Embedding(corpus_size, item_embedding_dim, sparse=sparse)
        else:
            self.input_embeddings = nn.Embedding(corpus_size + 1, input_embedding_dim, sparse=sparse, padding_idx=-1)
            if not self.two_tower:
                self.item_embeddings = nn.Embedding(corpus_size + 1, item_embedding_dim, sparse=sparse, padding_idx=-1)
        self.single_layer = single_layer

        print(self.single_layer)

        # if single_layer is True, it essentially become w2v model with single hidden layer
        if not self.single_layer:
            self.linear1 = nn.Linear(input_embedding_dim, hidden_dim1)
            self.linear2 = nn.Linear(hidden_dim1, item_embedding_dim)

            # self.linear1.weight.data.copy_(torch.eye(128))
            # self.linear2.weight.data.copy_(torch.eye(128))
            # self.linear1.bias.data.copy_(torch.tensor(0))
            # self.linear2.bias.data.copy_(torch.tensor(0))

            # self.linear1.weight.requires_grad = False
            # self.linear1.bias.requires_grad = False
            
            # self.linear2.weight.requires_grad = False
            # self.linear2.bias.requires_grad = False
        
            if self.two_tower:
                self.linear1_item = nn.Linear(input_embedding_dim, hidden_dim1)
                self.linear2_item = nn.Linear(hidden_dim1, item_embedding_dim)
                # self.linear1_item.weight.data.copy_(torch.eye(128))
                # self.linear2_item.weight.data.copy_(torch.eye(128))
                # self.linear1_item.data.copy_(torch.tensor(0))
                # self.linear2_item.data.copy_(torch.tensor(0))

        input_initrange = 1.0 / input_embedding_dim
        init.uniform_(self.input_embeddings.weight.data, -input_initrange, input_initrange)
        if not self.two_tower:
            item_initrange = 1.0 / item_embedding_dim
            init.uniform_(self.item_embeddings.weight.data, -item_initrange, item_initrange)

        if self.entity_type == 'word':
            self.input_embeddings.weight.data[-1] = 0
            if not self.two_tower:
                self.item_embeddings.weight.data[-1] = 0
    
    def forward_to_user_embedding_layer(self, pos_input, user_tower = True, in_chunks = False):
        # input embedding
        if in_chunks:
            embedding_lookup_func = self.embedding_lookup_n_chunk
        else:
            embedding_lookup_func = self.embedding_lookup
        

        if user_tower:
            emb_input = embedding_lookup_func(self.input_embeddings, pos_input)
            if self.single_layer:
                return emb_input
            else:
                h1 = F.relu(self.linear1(emb_input))
                output = F.relu(self.linear2(h1))
                return output

        else:
            emb_item = embedding_lookup_func(self.item_embeddings, pos_input)
            if self.single_layer:
                return emb_item
            else:
                h1 = self.linear1_item(emb_item)
                output = self.linear2_item(h1)
                return output


    def forward(self, pos_input, pos_item, neg_item):

        emb_user = self.forward_to_user_embedding_layer(pos_input, user_tower=True)

        # output embedding for positive instance
        emb_item = self.forward_to_user_embedding_layer(pos_item, user_tower=False)

        # output embedding for negative instance
        emb_neg_item = self.forward_to_user_embedding_layer(neg_item, user_tower=False)


        if self.normalize:
            emb_user = F.normalize(emb_user, p=2, dim=-1)
            emb_item = F.normalize(emb_item, p=2, dim=-1)
            emb_neg_item = F.normalize(emb_neg_item, p=2, dim=-1)

        score = torch.sum(torch.mul(emb_user, emb_item), dim=1) / self.temperature
        score = torch.clamp(score, max=10, min=-10)
        score = -F.logsigmoid(score)

        neg_score = torch.bmm(emb_neg_item, emb_user.unsqueeze(2)).squeeze() / self.temperature
        neg_score = torch.clamp(neg_score, max=10, min=-10)
        neg_score = -torch.sum(F.logsigmoid(-neg_score), dim=1)

        return torch.mean(score + neg_score)   

    def embedding_lookup(self, embedding, embed_index):
        if self.entity_type == 'page':
            emb_input = embedding(embed_index)
        elif self.entity_type == 'word':
            # need to fix lookup -1 embedding index should return 0 embedding vector
            # mean pooling
            select = (embed_index != embedding.padding_idx)
            sentence_emb_input = embedding(embed_index)
            emb_input = sentence_emb_input.sum(axis = -2) / select.sum(axis = -1).unsqueeze(-1)
        
        return emb_input
        
    def embedding_lookup_n_chunk(self, embedding, embed_index):
        chunks = torch.split(embed_index, 100000)
        return torch.cat([self.embedding_lookup(embedding, chunk) for chunk in chunks])